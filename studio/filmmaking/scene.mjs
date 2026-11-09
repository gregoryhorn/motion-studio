// Editable authored scene support: no fixed scene vocabulary or provider.
// Explicit layout is chosen by the author; time is seconds, never wall time.
export async function seekVideo(video,time){
  if(!Number.isFinite(time)||time<0)throw Error('Invalid footage time');
  const waitFor=(event,ready,act)=>new Promise((resolve,reject)=>{
    const done=()=>{if(ready()){clear();resolve();}};
    const fail=()=>{clear();reject(Error('Footage decode failed: '+(video.error?.message||video.currentSrc)));};
    const clear=()=>{clearTimeout(timer);video.removeEventListener(event,done);video.removeEventListener('error',fail);};
    const timer=setTimeout(()=>{clear();reject(Error('Footage readiness timed out: '+event));},10000);
    video.addEventListener(event,done);video.addEventListener('error',fail);
    try {if(video.error)return fail();act?.();done();} catch(e){clear();reject(e);}
  });
  video.pause();
  await waitFor('loadedmetadata',()=>video.readyState>=1);
  if(!Number.isFinite(video.duration)||time>=video.duration)throw Error('Footage source exhausted');
  if(video.currentTime!==time || video.seeking)
    await waitFor('seeked',()=>!video.seeking && Math.abs(video.currentTime-time)<1e-7,()=>{video.currentTime=time;});
  await waitFor('loadeddata',()=>video.readyState>=2);
}

export function bindScene({width,height,duration,fps=30,cuts=[],cues=[],render,ready=Promise.resolve()}){
  if(![width,height,fps].every(n=>Number.isInteger(n)&&n>0)||!Number.isFinite(duration)||duration<=0||typeof render!=='function')throw Error('Invalid scene contract');
  window.__film={width,height,duration,fps,cuts,cues};
  window.__ready=ready;
  window.__seek=async t=>{await ready; if(!Number.isFinite(t)||t<0||t>=duration)throw Error('Seek out of bounds');await render(t);};
  window.__samples=()=>4;
  window.__shutter=()=>1;
  if(!location.search.includes('render')) {
    let t=0,playing=false,last=0;
    const bar=document.createElement('input');bar.type='range';bar.min='0';bar.max=String(Math.max(0,duration-1/fps));bar.step=String(1/fps);
    Object.assign(bar.style,{position:'fixed',bottom:'12px',left:'5%',width:'90%',zIndex:9999});document.body.append(bar);
    let seeking=false;
    const show=async()=>{if(seeking)return;seeking=true;try{
      let requested;
      do {requested=t;await window.__seek(requested);} while(t!==requested);
    }catch(e){playing=false;window.__previewError=String(e);}
    finally{seeking=false;}};
    bar.oninput=()=>{t=+bar.value;show();};
    addEventListener('keydown',e=>{if(e.code==='Space'){playing=!playing;last=performance.now();e.preventDefault();}});
    const tick=now=>{if(playing){t=(t+(now-last)/1000)%duration;bar.value=String(t);show();}last=now;requestAnimationFrame(tick);};
    ready.then(()=>{window.__seek(0);requestAnimationFrame(tick);});
  }
}


