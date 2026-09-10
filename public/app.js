const $ = (s) => document.querySelector(s);
const form = $('#converter');
const help = {original:'Original preserves the source audio. No extra compression.',mp3:'MP3 at 320 kbps for broad compatibility. Re-encoding cannot improve the source.',wav:'Uncompressed WAV for editing. Larger files, with the same source quality.'};
form.addEventListener('change', () => $('#format-help').textContent = help[new FormData(form).get('format')]);
function status(message, error=false) { $('#result').hidden=false; $('#status').textContent=message; $('#status').className=error?'error':''; }
$('#paste').addEventListener('click', async () => { try { $('#url').value=await navigator.clipboard.readText(); $('#url').focus(); } catch { status('Clipboard access is unavailable. Paste your link into the field with ⌘V or Ctrl+V.'); $('#url').focus(); } });
let active = false;
form.addEventListener('submit', async (event) => {
 event.preventDefault(); if(active)return;
 let parsed; try { parsed=new URL($('#url').value); if(!['youtube.com','www.youtube.com','m.youtube.com','music.youtube.com','youtu.be'].includes(parsed.hostname)||!['http:','https:'].includes(parsed.protocol))throw Error(); }catch{return status('Please enter a valid youtube.com or youtu.be video link.',true);}
 active=true; $('#extract').disabled=true; $('#extract span').textContent='Extracting audio…'; $('#ready').hidden=true; $('#player').removeAttribute('src'); $('#progress').hidden=false; $('#progress').removeAttribute('value'); status('Finding the best audio source…');
 try {
  const response=await fetch('/api/convert',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:$('#url').value,format:new FormData(form).get('format')})});
  const data=await response.json(); if(!response.ok)throw Error(data.error||'Could not start conversion.');
  while(true){
   await new Promise(resolve=>setTimeout(resolve,1000));
   const poll=await fetch('/api/jobs/'+data.id); const job=await poll.json(); if(!poll.ok)throw Error(job.error);
   status(job.message); if(job.progress==null)$('#progress').removeAttribute('value');else $('#progress').value=job.progress;
   if(job.status==='error')throw Error(job.message);
   if(job.status==='complete'){
    $('#track-title').textContent=job.title; $('#file-info').textContent=`${job.format} · ${(job.size/1024/1024).toFixed(1)} MB · Available for this session`;
    $('#download').href='/download/'+data.id; $('#download').download=job.filename; $('#player').src='/download/'+data.id; $('#ready').hidden=false; break;
   }
  }
 }catch(error){status(error.message==='Failed to fetch'?'Cannot reach the conversion server. Check that DJ EDDY is running, then try again.':error.message,true);}
 finally{active=false;$('#extract').disabled=false;$('#extract span').textContent='Extract audio';$('#progress').hidden=true;}
});
