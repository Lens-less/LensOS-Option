export const CSV_HEADER='instrument_id,underlying,expiry,option_type,strike,bid,ask,quote_timestamp,settlement_currency,contract_multiplier,quote_unit,exercise_style,settlement_type,bid_size,ask_size,tick_size';
export function sampleCsv(version:'a'|'b'|'bad'='a'):string {
  const rows:string[][]=[];
  for(const asset of ['BTC','ETH'])for(const expiry of ['2026-10-22T08:00:00Z','2026-11-19T08:00:00Z'])for(const type of ['put','call']) {
    const base=asset==='BTC'?100000:2500;const step=asset==='BTC'?5000:100;
    const premiums=asset==='BTC'?[250,500,1000,2000,3500]:[10,25,50,85,130];
    for(let i=0;i<5;i++) {
      const strike=base+(i-2)*step;let premium=premiums[type==='put'?i:4-i];
      if(expiry.includes('11-19'))premium*=1.3;
      if(version==='b')premium*=1+(i-1)*.08;
      premium=Math.round(premium*100)/100;
      const spread=asset==='BTC'?50:3;
      rows.push([`SYNTHETIC-${asset}-${expiry.slice(0,10)}-${strike}-${type==='put'?'P':'C'}`,asset,expiry,type,String(strike),
        String(premium),String(Math.round((premium+spread)*100)/100),version==='b'?'2026-10-01T15:05:00Z':'2026-10-01T15:00:00Z',
        'USDC',asset==='BTC'?'0.1':'1','per_underlying','european','cash_linear',i===0?'':'10',i===0?'':'12',asset==='BTC'?'0.01':'0.01']);
    }
  }
  if(version==='bad') {
    rows[0][5]='99999';rows[1][9]='';rows[2][12]='inverse';rows[3][7]='2026-10-01 15:00';rows.push([...rows[4]]);
  }
  return [CSV_HEADER,...rows.map(row=>row.join(','))].join('\n')+'\n';
}
export function downloadText(name:string,text:string,type='text/plain;charset=utf-8'):void {
  const url=URL.createObjectURL(new Blob([text],{type}));const link=document.createElement('a');link.href=url;link.download=name;
  document.body.append(link);link.click();link.remove();window.setTimeout(()=>URL.revokeObjectURL(url),1000);
}
