"""#132 Phase16: test-page-only first-drag DOM/geometry read attribution.

Nothing is patched in the shipped application. Only bounded aggregate roles
are returned, not selectors, exact IDs, classes, DOM text or image bytes.
Wrapping browser layout reads itself perturbs timing, hence this is hypothesis
triage, NEVER proof of a forced synchronous layout or optimization speedup.
"""
from __future__ import annotations

from ops.canvas_phase12_isolation_111 import CPU_FACTORS

PROBE_JS=r"""arg=>{
  const op=typeof arg==="string"?arg:arg.op;
  if(op==="stop"){
    const s=window.__qa132draginit;
    if(!s)throw Error("phase16 observer missing on stop");
    try{
      for(const m of s.attr.takeRecords())s.classifyAttr(m);
      for(const m of s.child.takeRecords())s.classifyChild(m);
    }finally{
      s.attr.disconnect();s.child.disconnect();
      window.getComputedStyle=s.origComputed;
      Element.prototype.getBoundingClientRect=s.origRect;
      for(const [name,desc] of s.origOffsets)
        Object.defineProperty(HTMLElement.prototype,name,desc);
      delete window.__qa132draginit;
    }
    if(s.dropped>0)throw Error("phase16 probe event cap reached");
    return {phase:s.phase,reads:s.reads,
      rootAttributes:s.rootAttributes,childRecords:s.childRecords,
      mountCounts:s.mountCounts,
      mutationLineages:{added:s.lineageRows("added"),removed:s.lineageRows("removed")},
      offsetGettersTracked:s.origOffsets.length,
      restored:true,privateDomValuesPersisted:false,
      diagnosticOnly:true};
  }
  if(op!=="start" || window.__HANDRAW_TESTING__!==true ||
     window.__qa132draginit ||
     !["pre-input-idle","synthetic-move-1","synthetic-move-2",
       "synthetic-move-3"].includes(arg.phase))
    throw Error("invalid phase16 test probe activation");
  const vp=document.getElementById("ic-viewport");
  const layer=document.getElementById("ic-nodes-layer");
  const shell=document.querySelector(".ic-studio-shell");
  if(!vp||!layer||!shell)throw Error("native Stage16 canvas missing");
  const root=document.documentElement;
  const rootTargets=[root,document.body,shell,vp,layer];
  const overlay=document.getElementById("ic-overlay-layer");
  if(overlay)rootTargets.push(overlay);
  const role=el=>{
    if(!(el instanceof Element))return "other";
    if(el.matches("[data-float-topbar]")||el.closest("[data-float-topbar]"))
      return "floating-toolbar";
    if(el.matches(".ic-floating-overlay, #ic-overlay-layer, .ic-overlay-layer")||
       el.closest(".ic-floating-overlay, #ic-overlay-layer, .ic-overlay-layer"))
      return "overlay";
    if(el===vp)return "viewport";
    if(el===shell)return "canvas-shell";
    if(el===root||el===document.body)return "global-root";
    if(el===layer||layer.contains(el))return "node-layer";
    return "other";
  };
  // Emit only finite, static tag vocabulary and fixed landmark roles.
  // No ID, class, attribute value, selector, text, or media URL is recorded.
  const TAGS=new Set(["html","body","main","section","article","aside",
    "header","footer","nav","div","span","button","svg","g","path","rect",
    "circle","line","polygon","polyline","foreignobject","image","img",
    "canvas","figure","figcaption","picture","p","a","ul","ol","li",
    "input","textarea","label","form","select","option","dialog",
    "table","tbody","thead","tr","td","th","template"]);
  const safeTag=node=>{
    if(node.nodeType===3)return "#text";
    if(node.nodeType===8)return "#comment";
    if(!(node instanceof Element))return "#other-node";
    const tag=node.localName?.toLowerCase();
    return TAGS.has(tag)?tag:"other-tag";
  };
  const ancestry=parent=>{
    const tags=[];
    let cur=parent;
    while(cur && tags.length<24){
      tags.push(safeTag(cur));
      cur=cur.parentElement;
    }
    if(cur)throw Error("phase17 DOM ancestor depth exceeded");
    return tags.reverse();
  };
  const zero=()=>({"global-root":0,"canvas-shell":0,"viewport":0,
    "node-layer":0,"floating-toolbar":0,"overlay":0,"other":0});
  const s={phase:arg.phase,reads:{rect:zero(),computed:zero(),
      offsetWidth:zero(),offsetHeight:zero(),offsetTop:zero(),
      offsetLeft:zero()},
    rootAttributes:{class:zero(),style:zero()},
    childRecords:0,mountCounts:{added:zero(),removed:zero()},
    lineage:{added:new Map(),removed:new Map()},
    lineageRows:kind=>Array.from(s.lineage[kind].values())
      .sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b))),
    dropped:0,origComputed:window.getComputedStyle,
    origRect:Element.prototype.getBoundingClientRect,
    origOffsets:[],role,
  };
  s.classifyAttr=m=>{
    if(m.type!=="attributes")return;
    if(s.rootAttributes[m.attributeName]===undefined)return;
    if(++s.eventCount>256){s.dropped++;return}
    s.rootAttributes[m.attributeName][role(m.target)]++;
  };
  s.classifyChild=m=>{
    if(m.type!=="childList")return;
    if(++s.eventCount>256){s.dropped++;return}
    s.childRecords++;
    const parentRole=role(m.target);
    for(const kind of ["added","removed"]){
      const nodes=kind==="added"?m.addedNodes:m.removedNodes;
      for(const node of nodes){
        const r=node instanceof Element?role(node):parentRole;
        s.mountCounts[kind][r]++;
        // The removed node can already be detached when MutationObserver runs.
        // Preserve its mutation *parent* ancestry, not a misleading post-remove
        // closest()/contains() lookup against a detached child.
        const path=ancestry(m.target);
        const shape={ancestorTags:path,nodeTag:safeTag(node),
          parentRole,parentConnected:m.target.isConnected,count:1};
        const key=JSON.stringify([path,shape.nodeTag,parentRole,shape.parentConnected]);
        const old=s.lineage[kind].get(key);
        if(old)old.count++;
        else s.lineage[kind].set(key,shape);
        if(s.lineage[kind].size>64)throw Error("phase17 DOM lineage cardinality cap");
      }
    }
  };
  s.eventCount=0;
  s.attr=new MutationObserver(rows=>rows.forEach(s.classifyAttr));
  for(const el of new Set(rootTargets))
    s.attr.observe(el,{attributes:true,attributeFilter:["class","style"]});
  s.child=new MutationObserver(rows=>rows.forEach(s.classifyChild));
  s.child.observe(document.body,{childList:true,subtree:true});
  window.getComputedStyle=function(...args){
    s.reads.computed[role(args[0])]++;
    return s.origComputed.apply(this,args);
  };
  Element.prototype.getBoundingClientRect=function(...args){
    s.reads.rect[role(this)]++;
    return s.origRect.apply(this,args);
  };
  for(const name of ["offsetWidth","offsetHeight","offsetTop","offsetLeft"]){
    const desc=Object.getOwnPropertyDescriptor(HTMLElement.prototype,name);
    if(!desc||!desc.configurable||typeof desc.get!=="function")
      throw Error("phase16 offset getter unavailable: "+name);
    s.origOffsets.push([name,desc]);
    Object.defineProperty(HTMLElement.prototype,name,{
      configurable:desc.configurable,enumerable:desc.enumerable,
      get:function(){
        s.reads[name][role(this)]++;
        return desc.get.call(this);
      },
    });
  }
  window.__qa132draginit=s;
  return {installed:true,offsetGettersTracked:s.origOffsets.length};
}"""


def _validate_sample(name,sample):
    if name not in ("pre-input-idle","synthetic-move-1",
                    "synthetic-move-2","synthetic-move-3"):
        raise ValueError("unknown drag-init event window")
    if (not isinstance(sample,dict) or sample.get("phase")!=name
        or sample.get("restored") is not True
        or sample.get("offsetGettersTracked")!=4
        or sample.get("privateDomValuesPersisted") is not False):
        raise ValueError("unverified or incomplete drag-init trace")
    allowed={"global-root","canvas-shell","viewport","node-layer",
             "floating-toolbar","overlay","other"}
    reads=sample.get("reads")
    classes=sample.get("rootAttributes")
    mounts=sample.get("mountCounts")
    if (not isinstance(reads,dict) or set(reads)!={
        "rect","computed","offsetWidth","offsetHeight","offsetTop","offsetLeft"}
        or not isinstance(classes,dict) or set(classes)!={"class","style"}
        or not isinstance(mounts,dict) or set(mounts)!={"added","removed"}):
        raise ValueError("unexpected drag-init probe categories")
    for group in (reads,classes,mounts):
        for row in group.values():
            if (not isinstance(row,dict) or set(row)!=allowed or
                any(type(v) is not int or v<0 or v>20000 for v in row.values())):
                raise ValueError("unbounded/read of unexpected DOM category")
    lineages=sample.get("mutationLineages")
    if not isinstance(lineages,dict) or set(lineages)!={"added","removed"}:
        raise ValueError("missing precise test-only DOM mutation lineages")
    allowed_tags={"html","body","main","section","article","aside","header",
        "footer","nav","div","span","button","svg","g","path","rect",
        "circle","line","polygon","polyline","foreignobject","image","img",
        "canvas","figure","figcaption","picture","p","a","ul","ol","li",
        "input","textarea","label","form","select","option","dialog",
        "table","tbody","thead","tr","td","th","template",
        "#text","#comment","#other-node","other-tag"}
    for kind,rows in lineages.items():
        if not isinstance(rows,list) or len(rows)>64:
            raise ValueError("unbounded DOM lineage cardinality")
        seen=set()
        total=0
        for row in rows:
            if not isinstance(row,dict) or set(row)!={
                    "ancestorTags","nodeTag","parentRole","parentConnected","count"}:
                raise ValueError("unexpected DOM lineage shape")
            tags=row["ancestorTags"]
            if (not isinstance(tags,list) or not 1<=len(tags)<=24 or
                any(type(tag) is not str or tag not in allowed_tags for tag in tags)
                or row["nodeTag"] not in allowed_tags
                or row["parentRole"] not in allowed
                or type(row["parentConnected"]) is not bool
                or type(row["count"]) is not int or not 1<=row["count"]<=256):
                raise ValueError("untrusted/private DOM lineage content")
            ident=(tuple(tags),row["nodeTag"],row["parentRole"],
                   row["parentConnected"])
            if ident in seen:
                raise ValueError("duplicate DOM lineage record")
            seen.add(ident)
            total+=row["count"]
        if total!=sum(mounts[kind].values()):
            raise ValueError("DOM lineage/mount counts disagree")
    if type(sample.get("childRecords")) is not int or not 0<=sample["childRecords"]<=256:
        raise ValueError("unbounded DOM child mutation records")
    return {
        "phase":name,"reads":reads,"rootAttributes":classes,
        "mountCounts":mounts,"mutationLineages":lineages,
        "childRecords":sample["childRecords"],
        "offsetGettersTracked":4,
        "diagnosticOnly":True,
        "forcedSynchronousLayoutProven":False,
        "privateDomValuesPersisted":False,
    }


def collect(page,cdp):
    from ops.canvas_phase15_move_boundary_111 import one_trial
    observations={}
    for cpu in CPU_FACTORS:
        cdp.send("Emulation.setCPUThrottlingRate",{"rate":cpu})
        try:
            result=one_trial(page,cdp,probe=True)
            windows={}
            for name,row in result["windows"].items():
                probe=_validate_sample(name,row["phase16"])
                windows[name]={
                    "largeUpdateEvents":row["largeUpdateEvents"],
                    "maxElementCount":row["maxElementCount"],
                    "reasonCategories":row["reasonCategories"],
                    "structuralDomMutations":row["structure"],
                    "inputReadAndMountProbe":probe,
                }
            if not result["nativeGraphAndMediaUndoStable"]:
                raise RuntimeError("phase16 Graph/Undo/media invariants failed")
            observations[str(cpu)+"x"]=windows
        finally:
            cdp.send("Emulation.setCPUThrottlingRate",{"rate":1})
    return {
        "issue":132,"stage":16,
        "purpose":"first move: ancestor class, global overlay mount, geometry reads",
        "tracesByCpu":observations,
        "diagnosticOnly":True,"instrumentationPerturbsTiming":True,
        "forcedSynchronousLayoutProven":False,
        "productionOptimizationAuthorized":False,
        "physicalLowEndDeviceTested":False,
        "rawTracePersisted":False,"paidRequests":0,
        "decision":"NO-GO",
    }
