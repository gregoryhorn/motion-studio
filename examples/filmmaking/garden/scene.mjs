// Original local verification artwork: a fictional seed-library film.
// Portrait is composed independently, not cropped from landscape.
import {bindScene} from './scene-runtime.mjs';
import {E,clamp,lerp} from './core.js';
import cfg from './config.json' with {type:'json'};
const {width:pixelWidth,height:pixelHeight,panel,revised=false}=cfg, tall=pixelHeight>pixelWidth;
// Two authored layouts in logical pixels; raster scale is not layout selection.
const W=tall?540:960,H=tall?960:540;
const c=document.querySelector('canvas'); c.width=pixelWidth;c.height=pixelHeight;
const g=c.getContext('2d'), image=new Image();image.src='./seed.png';
const ready=Promise.all([image.decode(),document.fonts.load('800 90px Archivo'),document.fonts.load('500 20px Inst')]);
const bg='#f0ebdc',ink='#203a2c',accent='#cc5832';
function text(s,x,y,size,color=ink,weight=800){g.fillStyle=color;g.font=`${weight} ${size}px Archivo`;g.fillText(s,x,y);}
function line(x,y,X,Y,color=ink){g.strokeStyle=color;g.lineWidth=1;g.beginPath();g.moveTo(x,y);g.lineTo(X,Y);g.stroke();}
function label(s,x,y){g.fillStyle=ink;g.font='500 12px Inst';g.fillText(s,x,y);}
function circle(x,y,r,color){g.fillStyle=color;g.beginPath();g.arc(x,y,r,0,Math.PI*2);g.fill();}
function frame(t){
 g.setTransform(pixelWidth/W,0,0,pixelHeight/H,0,0);
 g.fillStyle=bg;g.fillRect(0,0,W,H);
 const m=40,u=E.outQuint(clamp(t/.85)),v=E.inOutCubic(clamp((t-.25)/1.2));
 label('FIELDNOTES / SEED LIBRARY',m,32);label(`0${panel+1} / 03`,W-87,32);
 line(m,48,W-m,48,'#b4bdab');
 if(panel===0){
   const x=tall?W/2:W*.73,y=tall?H*.61:H*.54,r=tall?W*.41:H*.43;
   circle(x,y,r,'#d8dfc8');circle(x,y,r*.82,'#e6e6d1');
   g.save();g.translate(x,y+lerp(60,0,u));g.rotate(lerp(-.18,.05,v));
   const s=(tall?W*.78:H*.9)*(1+.025*Math.sin(t));g.drawImage(image,-s/2,-s/2,s,s);g.restore();
   g.save();g.translate(0,lerp(30,0,u));g.globalAlpha=u;
   text('Small',m,tall?H*.18:H*.40,tall?76:94);text('beginnings.',m,tall?H*.27:H*.58,tall?68:78);
   label('A little care. A different tomorrow.',m,tall?H*.33:H*.69);g.restore();
   label('COLLECT  /  CULTIVATE  /  SHARE',m,H-30);
 } else if(panel===1){
   text('Make room',m,tall?140:140,tall?58:70);text('for growth.',m,tall?210:215,tall?58:70);
   const X=tall?m:W*.49,Y=tall?H*.36:90, cw=tall?W-2*m:W*.46,ch=tall?H*.48:H*.68;
   g.fillStyle='#203a2c';g.beginPath();g.roundRect(X,Y,cw,ch,15);g.fill();
   text('YOUR GROWING PLAN',X+22,Y+35,13,'#e9ebdd',500);
   const names=['Choose a seed','Find its light','Give it time'];
   names.forEach((s,i)=>{const y=Y+85+i*(ch-100)/3,p=E.outCubic(clamp((t-.2-i*.22)/.55));
      line(X+22,y+36,X+cw-22,y+36,'#52664e');circle(X+30,y,9,'#cc704b');
      text(s,X+53,y+5,tall?19:21,'#f0ebdc',500);
      g.strokeStyle='#f0ebdc';g.lineWidth=2;g.beginPath();g.moveTo(X+26,y);g.lineTo(X+29,y+3*p);g.lineTo(X+35,y-4*p);g.stroke();});
   const p=clamp((t-.5)/1.6);g.fillStyle='#4d654c';g.fillRect(X+22,Y+ch-28,cw-44,4);g.fillStyle='#cc704b';g.fillRect(X+22,Y+ch-28,(cw-44)*p,4);
   label('Not a dashboard. A small daily ritual.',m,H-55);
 } else {
   const x=tall?W/2:W*.78,y=tall?H*.67:H*.55;
   g.save();g.translate(x,y);const s=tall?250:290;g.rotate(-.18+.04*v);g.drawImage(image,-s/2,-s/2,s,s);g.restore();
   text(revised?'Good things':'The future',m,tall?H*.21:H*.37,tall?66:86);
   text(revised?'take care.':'is growing.',m,tall?H*.30:H*.55,tall?66:86);
   label('START SMALL. KEEP GOING.',m,tall?H*.38:H*.67);
   g.fillStyle=accent;g.beginPath();g.roundRect(m,H-108,tall?W-2*m:290,48,24);g.fill();
   text('Plant something good  \u2197',m+23,H-77,18,'#fff5e8',500);
   label('Original verification film / fictional seed-library brief',m,H-26);
 }
}
bindScene({width:pixelWidth,height:pixelHeight,duration:3,fps:30,render:frame,ready,
 cues:[{time:0,event:'scene-enter'},{time:.8,event:'picture-enter'}]});
