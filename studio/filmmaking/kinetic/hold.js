import { Scene } from './blocks.js';
import { el, C } from './core.js';
// Quiet/readable block: no compulsory motion, FX, or sound. Text remains editable.
export class Hold extends Scene {
  build() {
    const o=this.o;
    Object.assign(this.root.style,{display:'flex',flexDirection:'column',justifyContent:'center',alignItems:'center',padding:'100px',gap:'32px',textAlign:'center',boxSizing:'border-box'});
    if(o.ground) this.f.ground(this.t0,this.t1,C[o.ground]||o.ground);
    this.text=el('div',this.root,'',{fontFamily:'Archivo',fontWeight:'800',fontSize:(o.size||120)+'px',lineHeight:'1.08',maxWidth:'100%',overflowWrap:'anywhere',color:C[o.color]||o.color||C.paper});
    this.text.textContent=o.text||'';
    if(o.sub){const sub=el('div',this.root,'',{fontFamily:'Inst',fontSize:(o.subSize||48)+'px',maxWidth:'1400px',color:C[o.color]||o.color||C.paper});sub.textContent=o.sub;}
  }
  update(){this.root.style.display="flex";}
  cam(){return {x:0,y:0,s:1,r:0};}
}
