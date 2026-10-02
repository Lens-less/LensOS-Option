/** Explicit ISO instants only. Date.parse alone silently normalizes e.g. 30 February. */
export function isoInstant(value:string):string|null {
  const match=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if(!match)return null;
  const [,year,month,day,hour,minute,second,,zone]=match;
  const y=Number(year),m=Number(month),d=Number(day);
  if(y<1000||m<1||m>12||d<1||d>new Date(Date.UTC(y,m,0)).getUTCDate()||Number(hour)>23||Number(minute)>59||Number(second??0)>59)return null;
  if(zone!=='Z'){const h=Number(zone.slice(1,3)),min=Number(zone.slice(4));if(h>14||min>59||(h===14&&min!==0))return null;}
  const milliseconds=Date.parse(value);return Number.isFinite(milliseconds)?new Date(milliseconds).toISOString():null;
}
