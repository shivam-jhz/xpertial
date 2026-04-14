export const fmtCost = (usd: number) => usd < 0.01 ? `$${usd.toFixed(4)}` : usd < 10 ? `$${usd.toFixed(2)}` : `$${usd.toFixed(1)}`;
export const fmtInr = (inr: number) => `₹${Math.round(inr).toLocaleString('en-IN')}`;
export const fmtDur = (s: number) => { const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=Math.floor(s%60); return h>0?`${h}h ${m}m ${sec}s`:`${m}m ${sec}s`; };
export const fmtLoss = (v: number|null|undefined) => v==null?'—':v.toExponential(3);
export const relTime = (iso: string) => { const s=Math.floor((Date.now()-new Date(iso).getTime())/1000); if(s<60)return`${s}s ago`; if(s<3600)return`${Math.floor(s/60)}m ago`; return`${Math.floor(s/3600)}h ago`; };
