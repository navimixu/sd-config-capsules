from pydantic import BaseModel, Field, ValidationError
from urllib.parse import urlparse, parse_qs, urlunparse
import requests, json, os
from pathlib import Path

EXT_NAME = "Config Capsules"
LOG_CHANNELS = ["DEBUG","WARN","CRITICAL", "INFO"]


SITE_OPT = {
    "civitai":{},
    "gelbooru":{
        "general":0,
        "characters":4,
        "artists":1,
        "misc":5,
        "copyright":3
    },
    "danbooru":{
        "general":"tag_string_general",
        "characters":"tag_string_character",
        "artists":"tag_string_artist",
        "misc":"tag_string_meta",
        "copyright":"tag_string_copyright"
    }
}


def cc_log(msg, channel:int=3):
    if not channel == 0: #Debugger off
        print(f"[{EXT_NAME}][{LOG_CHANNELS[channel]}] {msg}")

def curate_booru_tags(tabs_sequance:str)-> tuple[int, int] : 
    tabs_sequance.replace(" ",", ").replace("_"," ").replace("(","\(").replace(")","\)")

def recalculate_resolution(height:int, width:int, SD_mode:bool =False): #SD_mode NYI
    SDXL_DIMS = {
        1.0     :{ "label":"Square", "height":1024, "width":1024 },
        
        1.286   :{ "label":"Portrait", "height":1152, "width":896 },
        0.778   :{ "label":"Landscape", "height":896, "width":1152 },
        
        1.462   :{ "label":"Portrait Photo", "height":1216, "width":832 },
        0.684   :{ "label":"Landscape Photo", "height":832, "width":1216 },
        
        1.750   :{ "label":"Wide Portrait", "height":1344, "width":768 },
        0.571   :{ "label":"Wide Landscape", "height":768, "width":1344 },

        2.4     :{ "label":"Photo Strip", "height":1536, "width":640 },
        0.417   :{ "label":"Cinematic", "height":640, "width":1536 }
    }

    ref_ratio =  height/width
    selected_ratio = 1.0
    for ratio, dim in SDXL_DIMS.items():
        selected_ratio = selected_ratio if abs(selected_ratio - ref_ratio) < abs(ratio - ref_ratio) else ratio 
    
    cc_log(f'resolution set as [{SDXL_DIMS[selected_ratio]["height"]}]')
    return (SDXL_DIMS[selected_ratio]["height"], SDXL_DIMS[selected_ratio]["width"])


class GenMetadata(BaseModel):
    prompt: str = Field(default="")
    neg_prompt: str = Field(default="")
    cfg_scale: float = Field(default=7.0)
    steps: int = Field(default=20)
    seed: int = Field(default=-1)
    height: int = Field(default=1024)
    width: int = Field(default=1024)
    sampling: str = Field(default="")
    scheduler: str = Field(default="")
    found_props: list[str] = Field(default_factory=list)
    src: str = Field(default="")
    post_id: int = Field(default=0)

 
    @classmethod
    def from_civi_api(cls, meta: dict):
        # Required fields mapping to their keys in the API response
        # add by post https://civitai.com/api/v1/images?postId=9958104
        meta = meta.get("result", {}).get("data", {}).get("json", {}).get("meta", {})
        is_comfy = meta.get("result", {}).get("data", {}).get("json", {}).get("process", "").lower() == "comfy"
        if not meta or is_comfy:
            raise ValueError("Metadata was not found in response")
        
        extracted_data = {}
        found_props = []
        fields_mapping = {
            "prompt": "prompt",
            "neg_prompt": "negativePrompt",
            "cfg_scale": "cfgScale",
            "steps": "steps",
            "seed": "seed",
            "sampling": "sampler",
            "scheduler": "Schedule type"
        }

        # Extract values and track missing properties
        for field_name, api_key in fields_mapping.items():
            value = meta.get(api_key)
            if value is not None:
                found_props.append(field_name)
                extracted_data[field_name] = value

        # Extract size and split into height and width
        size = meta.get("Size", "0x0").split("x")
        try:
            height, width = map(int, size)
            found_props+= ["height", "width"]
        except ValueError:
            height, width = 0, 0

        # Add size-related data
        extracted_data["height"] = height
        extracted_data["width"] = width
        extracted_data["found_props"] = found_props
        extracted_data["src"] = "civitai"
        extracted_data["post_id"] = meta.get("id",0)

        return cls(**extracted_data)
    
    @classmethod
    def from_dan_api(cls, meta: dict):
        if not meta :
            raise ValueError("Metadata not found in response")
        
        extracted_data = {}
        hd = meta.get("image_height")
        wd = meta.get("image_width")
        if wd and hd:
            extracted_data["height"], extracted_data["width"] = recalculate_resolution(hd, wd)
        
        extracted_data["prompt"] = meta.get("tag_string")
        extracted_data["found_props"] = ["prompt", "width", "height"]
        extracted_data["src"] = "danbooru"
        extracted_data["post_id"] = meta.get("id",0)

        return cls(**extracted_data)

    @classmethod
    def from_gel_api(cls, meta: dict):
        meta = meta.get("post")
        if not meta or not meta[0]:
            raise ValueError("Metadata not found in response")
        else:
            meta = meta[0]
        
        extracted_data = {}
        hd = meta.get("height")
        wd = meta.get("width")
        if wd and hd:
            extracted_data["height"], extracted_data["width"] = recalculate_resolution(hd, wd)
        extracted_data["prompt"] = meta.get("tags")
        extracted_data["found_props"] = ["prompt", "width", "height"]
        extracted_data["src"] = "gelbooru"
        extracted_data["post_id"] = meta.get("id",0)

        return cls(**extracted_data)
    
    def reprc_with_opts (self, selected_opts=[]):
        if self.src == "gelbooru":
            selected_opts = selected_opts if selected_opts else ["artists", "general", "characters"]
            gel_tags_endpoint  = r'https://gelbooru.com/index.php?page=dapi&s=tag&q=index&json=1&orderby=count&names=#TAGS#'.replace("#TAGS#", self.prompt)
            selected_opts_ids = [SITE_OPT["gelbooru"][key] for key in selected_opts]
            filtered_tags = []
            filtered_artists = []
            filtered_chara = []
            cleaned_tags = []
            #ee = ee.replace(" ",", ").replace("_"," ").replace("(","\(").replace(")","\)")
            try:
                cc_log(f"requesting from endpoint:  {gel_tags_endpoint}", 3)
                response = requests.get(gel_tags_endpoint)
                response.raise_for_status()  # Raise an exception for HTTP errors
                data = response.json()
                tags_pool = data.get("tag", [])
                for tag in tags_pool:
                    if tag.get("type",-1) in selected_opts_ids:
                        if tag.get("type") == 1:
                            filtered_artists.append("by "+tag.get("name",""))
                        elif tag.get("type") == 4: 
                            filtered_chara.append(tag.get("name",""))
                        else:
                            filtered_tags.append(tag.get("name",""))
                    else:
                        cleaned_tags.append(tag.get("name",""))
                
                cc_log(f"tags removed {cleaned_tags}", 0)
                filtered_tags = filtered_artists + filtered_chara + filtered_tags
                self.prompt = ", ".join(filtered_tags).replace("_"," ").replace("(","\(").replace(")","\)")

            except requests.exceptions.RequestException as e:
                cc_log(f"HTTP Request failed: {e}", 2)
            except ValidationError as e:
                cc_log(f"Validation Error: {e}", 2) 
            #except ValueError as e:  cc_log(f"Data formulation failed: {e}", 2)
        
        elif self.src == "danbooru":
            selected_opts = selected_opts if selected_opts else ["artists", "general", "characters"]
            gel_tags_endpoint  = r'https://danbooru.donmai.us/posts/#ID#.json'.replace("#ID#", f"{self.post_id}")
            selected_opts_ids = [SITE_OPT["danbooru"][key] for key in selected_opts]
            filtered_tags = []
            filtered_artists = []
            filtered_chara = []
            cleaned_tags = []
            #ee = ee.replace(" ",", ").replace("_"," ").replace("(","\(").replace(")","\)")
            try:
                cc_log(f"requesting from endpoint:  {gel_tags_endpoint}", 3)
                response = requests.get(gel_tags_endpoint)
                response.raise_for_status()  # Raise an exception for HTTP errors
                data = response.json()
                for key , data_key in SITE_OPT["danbooru"].items():
                    if key in selected_opts:
                        if key == "artists":
                            filtered_artists = data.get(data_key,"").split(" ")
                        elif key == "character":
                            filtered_chara = data.get(data_key,"").split(" ")
                        else:
                            filtered_tags+= data.get(data_key,"").split(" ")
                    else:
                        cleaned_tags+= data.get(data_key,"").split(" ")
  
                cc_log(f"tags removed {cleaned_tags}", 0)
                filtered_artists = [f"by {artist}" for artist in filtered_artists]
                filtered_tags = filtered_artists + filtered_chara + filtered_tags
                self.prompt = ", ".join(filtered_tags).replace("_"," ").replace("(","\(").replace(")","\)")

            except requests.exceptions.RequestException as e:
                cc_log(f"HTTP Request failed: {e}", 2)
            except ValidationError as e:
                cc_log(f"Validation Error: {e}", 2) 



    
    def save_as_named_entry(self, file_path: str, entry_name: str):
        """
        Save the ConfigData instance as a named entry in a JSON file.

        Args:
            file_path (str): Path to the JSON file.
            entry_name (str): Key under which the ConfigData instance will be saved.
        """
        try:
            # Load existing data if the file exists, otherwise create a new dictionary
            file = Path(file_path)
            file.parent.mkdir(parents=True, exist_ok=True)
            if file.exists():
                with open(file_path, "r") as f:
                    data = json.load(f)
            else:
                data = {}

            # Update or add the entry
            data[entry_name] = self.dict()

            # Save the updated data back to the file
            with open(file_path, "w") as f:
                json.dump(data, f, indent=4)
            cc_log(f"ConfigData saved under '{entry_name}' in {file_path}")
            return True
        except Exception as e:
            cc_log(f"Failed to save ConfigData: {e}",1)
            return False

    @classmethod
    def from_named_entry(cls, file_path: str, entry_name: str):
        file = Path(file_path)

        if not file.exists():
            #raise FileNotFoundError(f"The file '{file_path}' does not exist.")
            cc_log(f"The file '{file_path}' does not exist.", channel=1)
            return None

        with file.open("r") as f:
            data = json.load(f)

        if entry_name not in data:
            #raise KeyError(f"Entry '{entry_name}' not found in '{file_path}'.")
            cc_log(f"Entry '{entry_name}' not found in '{file_path}'.", channel=1)
            return None

        entry_data = data[entry_name]

        try:
            return cls(**entry_data)
        except Exception as e:
            cc_log(f"Invalid data for ConfigData: {e}", channel=2)
            return None
            #raise ValueError(f"Invalid data for ConfigData: {e}")

META_PROPS = [field for field in GenMetadata.model_fields.keys() if field not in ["found_props"]]

def request_from_civitai (url:str):
    res = ""
    api_endpoint = r'https://civitai.com/api/trpc/image.getGenerationData?input={"json":{"id":##ID##}}'
    parsed_url = urlparse(url)
    url = urlunparse(parsed_url._replace(query=""))
    if "images" in url.lower():
        res = api_endpoint.replace("##ID##",url.split("/")[-1])
    else:
        cc_log("invalid url",2)
    return res


def request_from_danbooru (url:str):
    res = ""
    parsed_url = urlparse(url)
    url = urlunparse(parsed_url._replace(query=""))
    if "/posts/" in url.lower():
        res = url+".json"
    else:
        cc_log("invalid url",2)
    return res

def request_from_gelbooru (url:str):
    res = ""
    api_endpoint = r'https://gelbooru.com/index.php?page=dapi&s=post&q=index&json=1&limit=1&id=##ID##'
    parsed_url = urlparse(url)
    id_param = parse_qs(parsed_url.query).get('id', [None])[0]
    if "page=post" in url.lower() and id_param:
        res = api_endpoint.replace("##ID##",id_param)
    else:
        cc_log("invalid url",2)
    return res

def fetch_and_create_object(api_url: str, req_type:str = ""):
    config_object = GenMetadata()
    try:
        # Send a GET request to the API
        cc_log(f"requesting from endpoint:  {api_url}", 3)
        response = requests.get(api_url)
        response.raise_for_status()  # Raise an exception for HTTP errors
        data = response.json()
        if req_type == "civitai":
            config_object = GenMetadata.from_civi_api(data)
        elif req_type == "gelbooru":
            config_object = GenMetadata.from_gel_api(data)
        elif req_type == "danbooru":
            config_object = GenMetadata.from_dan_api(data)

            

    except requests.exceptions.RequestException as e:
        cc_log(f"HTTP Request failed: {e}", 2)
    except ValidationError as e:
        cc_log(f"Validation Error: {e}", 2)
    except ValueError as e:
        cc_log(f"Data extraction failed: {e}", 2)
    return config_object

def processUserInput(postUrl:str ,local_db_file:str=None)->tuple[GenMetadata,list]:
    postUrl = postUrl.strip()
    req_type  = ""
    api_req = ""
    aux_opt = {}
    reproc_fn = None
    
    if postUrl.startswith("@") and local_db_file:
        entry = postUrl.replace("@","").lower()
        return GenMetadata.from_named_entry(entry_name=entry, file_path= local_db_file), []
    elif "civitai.com" in postUrl.lower():
        req_type  = "civitai"
        aux_opt = SITE_OPT.get(req_type,{})
        api_req = request_from_civitai(postUrl)
    elif "gelbooru.com" in postUrl.lower():
        req_type  = "gelbooru"
        aux_opt = SITE_OPT.get(req_type,{})
        api_req = request_from_gelbooru(postUrl)
    elif "danbooru.donmai.us" in postUrl.lower():
        req_type  = "danbooru"
        aux_opt = SITE_OPT.get(req_type,{})
        api_req = request_from_danbooru(postUrl)


    return fetch_and_create_object(api_req, req_type), list(aux_opt.keys())


