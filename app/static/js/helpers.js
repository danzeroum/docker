function fmtBytes(bytes) {
  if (bytes == null) return '—';
  const units = ['B','KB','MB','GB','TB'];
  let i = 0;
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
  return `${bytes.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function fmtDuration(ms){
  if(!ms || ms < 0) return '—';
  const s = Math.floor(ms/1000);
  const d = Math.floor(s/86400);
  const h = Math.floor((s%86400)/3600);
  const m = Math.floor((s%3600)/60);
  const sec = s%60;
  if(d>0) return `${d}d ${h}h ${m}m`;
  if(h>0) return `${h}h ${m}m`;
  if(m>0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

function fmtDate(d){
  if(!d) return '—';
  return new Date(d).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
}

function shortId(id){return id ? id.substring(0,12) : '—';}

function escapeHtml(s){
  if (s == null) return '';
  return String(s).replace(/[&<>"]/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]
  ));
}
