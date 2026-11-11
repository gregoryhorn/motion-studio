// Shared exact retained-byte verification for Quick Create and Production.
const digest=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
const fault=code=>Object.assign(new Error(code),{code});
export async function readRetained(client,operation,identity,valid){
  const requested=identity(),requestedTake=requested.take;
  let offset=0,total=null,expected=null,mime=null,descriptor=null;const parts=[];
  do{
    const chunk=await client.request(operation,{...requested,offset});
    if(!valid())throw fault('RETAINED_SCOPE_CHANGED');
    let part;try{part=Uint8Array.from(atob(chunk.bytes),c=>c.charCodeAt(0));}catch{throw fault('CREATION_INTEGRITY_FAILED');}
    if(chunk.take!==requestedTake||chunk.offset!==offset||!Number.isInteger(chunk.total)||chunk.total>16777216||
      chunk.total<1||part.length<1||part.length>49152||offset+part.length>chunk.total||
      (total!==null&&(chunk.total!==total||chunk.sha256!==expected||chunk.mime!==mime))||await digest(part)!==chunk.chunk_sha256)throw fault('CREATION_INTEGRITY_FAILED');
    if(!valid())throw fault('RETAINED_SCOPE_CHANGED');
    total=chunk.total;expected=chunk.sha256;mime=chunk.mime;descriptor=chunk.descriptor;parts.push(part);offset+=part.length;
  }while(offset<total);
  const bytes=new Uint8Array(total);let cursor=0;for(const part of parts){bytes.set(part,cursor);cursor+=part.length;}
  if(await digest(bytes)!==expected)throw fault('CREATION_INTEGRITY_FAILED');
  if(!valid())throw fault('RETAINED_SCOPE_CHANGED');
  return {bytes,sha256:expected,take:requestedTake,mime,descriptor};
}
