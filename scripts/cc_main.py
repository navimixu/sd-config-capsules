import gradio as gr
from scripts.cc_utils import GenMetadata, EXT_NAME, META_PROPS, processUserInput, cc_log
import modules.scripts as scripts 
import os

CAP_DB_FILE = os.path.join(scripts.basedir(),"userdata","saved_capsules.json")
fetched_metadata:GenMetadata = None
meta_comps = { "img2img":{}, "txt2img":{}}
ext_modes = ["Use Mode", "Edit Mode"]

#----------[Gr Events]---------
def act_fetch_data(txt_url):
    global fetched_metadata
    global source_location
    fetched_metadata, extra_opt = processUserInput(txt_url, local_db_file=CAP_DB_FILE)
    cc_log(f"{fetched_metadata}", 0)
    choices_list = fetched_metadata.found_props if fetched_metadata else []
    if not fetched_metadata:
        gr.Info("No data was loaded")
    return(
        gr.update(visible= bool(fetched_metadata), choices=choices_list),
        gr.update(visible= bool(fetched_metadata)and bool(extra_opt), choices=extra_opt),
        gr.update(visible= bool(fetched_metadata)and bool(fetched_metadata.found_props))
    )

def act_send_to_ui(sel_props, sel_aux_props, sel_tab_mode):
    global meta_comps
    global fetched_metadata
    
    fetched_metadata.reprc_with_opts(sel_aux_props)
    new_updates = ()
    for prop, comp in meta_comps[sel_tab_mode].items():
        new_val = getattr(fetched_metadata,prop) if fetched_metadata and prop in sel_props else None
        if new_val:
            cc_log(f'new value of [{prop}]: {new_val}', 0)
            new_updates = new_updates + (gr.update(value= new_val), )
        else:
            #old_val  = getattr(comp,"value")
            new_updates = new_updates + (gr.skip(), )

    return new_updates

def act_quick_apply(txt_url, sel_tab_mode):
    global fetched_metadata
    global meta_comps

    fetched_metadata, extra_opt = processUserInput(txt_url, local_db_file=CAP_DB_FILE)
    cc_log(f"{fetched_metadata}", 0)
    if not fetched_metadata:
        gr.Info("No data was loaded")
    
    choices_list = fetched_metadata.found_props if fetched_metadata else []
    return act_send_to_ui(choices_list, [], sel_tab_mode)

def toggle_edit_mode(ck_edit_mode, sel_tab_mode):
    ck_edit_mode = ck_edit_mode== ext_modes[1] 
    txt_label  = "Config Capsule Name" if ck_edit_mode else "Source Url"
    txt_info  = "" if ck_edit_mode else "Can either be a Civitai post, a Gelbooru post or saved capsule" 
    return(
        gr.update(visible= ck_edit_mode, choices=list(meta_comps[sel_tab_mode].keys())),
        gr.update(visible= False),
        gr.update(label= txt_label, placeholder= txt_info),
        gr.update(visible= not ck_edit_mode),
        gr.update(visible= False),
        gr.update(visible= ck_edit_mode)
)

def act_save_capsule(sel_tab_mode, cap_name, sel_props, *ui_comps):
    cap_name = cap_name.lower().strip().replace("@","") if isinstance(cap_name, str) else ""
    if not cap_name:
        gr.Info(f"Config Capsule needs a name")
        return
    
    prop_components = meta_comps.get(sel_tab_mode,{})
    capsule = GenMetadata()
    ordered_comps= list(ui_comps)
    for index, (prop, comp) in enumerate(prop_components.items()):
        if prop in sel_props:
            val = ordered_comps[index] if ordered_comps[index] else getattr(comp,"value")
            setattr(capsule, prop, val)
            capsule.found_props.append(prop)
    cc_log(capsule)
    
    if capsule.save_as_named_entry(entry_name=cap_name,  file_path=CAP_DB_FILE):
        gr.Info(f"Config Capsule [{cap_name}] saved")
    else:
        gr.Info(f"Config Capsule [{cap_name}] was not saved")
#-----------[Gr Ui]-----------
class Script(scripts.Script):

    # Function to set title
    def title(self):
        return EXT_NAME

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    
    def ui(self, is_img2img):
        tab_prefix = {True:"img2img", False:"txt2img"}
        with gr.Accordion(label=EXT_NAME, open=False):
            sel_tab_mode = gr.Radio(visible= False, choices=list(tab_prefix.values()), value= tab_prefix[is_img2img], interactive=False)
            with gr.Row():
                sel_ext_mode    = gr.Dropdown (label="Mode", choices= ext_modes, value=ext_modes[0] ,elem_id="ncc_mode" )
                txt_url         = gr.Textbox(elem_id="ncc_txt_box",  label="Source Url", placeholder="Can be a Saved Capsule or an image url from Civitai, Gelbooru or Danbooru")
                btn_fetch       = gr.Button("Fetch" , elem_id= "ncc_btn_fetch")
            sel_props       = gr.CheckboxGroup(label="Capsule configs", choices=META_PROPS, visible= False)
            sel_aux_props   = gr.CheckboxGroup(label="Addional options", choices=[], visible= False)
            btn_remix       = gr.Button("Apply Capsule", visible= False, variant="primary")
            btn_save        = gr.Button("Save Capsule", visible= False, variant="primary")
            
            
                

        btn_fetch.click     (act_fetch_data,  inputs=[txt_url], outputs=[sel_props,sel_aux_props, btn_remix])
        btn_remix.click     (act_send_to_ui,  inputs=[sel_props, sel_aux_props, sel_tab_mode], outputs=list(meta_comps[tab_prefix[is_img2img]].values()))
        txt_url.submit      (act_quick_apply,  inputs=[txt_url, sel_tab_mode], outputs=list(meta_comps[tab_prefix[is_img2img]].values()))
        
        sel_ext_mode.select (toggle_edit_mode,  inputs=[sel_ext_mode, sel_tab_mode], outputs=[sel_props, sel_aux_props, txt_url, btn_fetch, btn_remix, btn_save])
        btn_save.click      (act_save_capsule,  inputs=[sel_tab_mode, txt_url, sel_props] + list(meta_comps.get(tab_prefix[is_img2img],{}).values())) 
    
    def after_component(self, component, **kwargs):
        tab_prefix = ["txt2img", "img2img"]
        for tab in tab_prefix:
            for prop in META_PROPS:
                if kwargs.get("elem_id") == f"{tab}_{prop}":
                    if not meta_comps.get(tab):
                        meta_comps[tab] = {}
                    meta_comps[tab][prop] = component
                    break
 