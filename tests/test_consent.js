'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {parseChoice,locationForAds,consentValues}=require('../consent.js');
let checks=0;function check(value){assert.ok(value);checks++;}
const now=Date.now(),valid=ads=>JSON.stringify({version:1,ads,at:now});
for(const raw of [null,'bad','{}',JSON.stringify({version:2,ads:true,at:now}),JSON.stringify({version:1,ads:'yes',at:now}),JSON.stringify({version:1,ads:true,at:now+1000}),JSON.stringify({version:1,ads:true,at:now-181*86400000})])check(parseChoice(raw,now)===null);
check(parseChoice(valid(false),now).ads===false);check(parseChoice(valid(true),now).ads===true);
check(locationForAds('https://abrechnungs-navi.de/?email=secret@example.invalid&gclid=valid123#private')==='https://abrechnungs-navi.de/?gclid=valid123');
check(locationForAds('https://abrechnungs-navi.de/?gclid=bad%40identifier')==='https://abrechnungs-navi.de/');
check(consentValues(true).ad_personalization==='denied' && consentValues(true).analytics_storage==='denied');
function fixture(path='/',stored=null){
  const scripts=[],fetches=[],cookies=[],redirects=[],history=[],elements=[];
  class Element{
    constructor(tag){this.tag=tag;this.listeners={};this.children={};this.dataset={};this.checked=false;this.hidden=false;}
    setAttribute(){} addEventListener(type,fn){this.listeners[type]=fn;}
    querySelector(selector){if(selector==='input[name="ads_consent"]')return this.children.ads_consent||null;return this.children[selector]||(this.children[selector]=new Element('control'));}
    querySelectorAll(selector){if(selector==='[data-choice]'){if(!this.choices)this.choices=['false','true'].map(v=>{const e=new Element('button');e.dataset.choice=v;return e;});return this.choices;}return [];}
    appendChild(e){this.children[e.name]=e;} showModal(){this.open=true;} close(){this.open=false;}
  }
  const data=new Map(stored?[['an_consent_v1',stored]]:[]),form=new Element('form');
  const document={referrer:'https://other.invalid/private?email=secret',createElement:tag=>new Element(tag),getElementById:id=>id==='anfrage-form'?form:null,body:{append(...args){elements.push(...args);}},head:{appendChild(e){scripts.push(e);}}};
  Object.defineProperty(document,'cookie',{get:()=> '_gcl_aw=test; normal=keep',set:v=>cookies.push(v)});
  const root={document,AN_ADS_CONFIG:{enabled:true,id:'AW-12345',label:'FAKE_TEST_ONLY'},location:{pathname:path,href:'https://abrechnungs-navi.de'+path+'?email=secret&gclid=abc',origin:'https://abrechnungs-navi.de',hostname:'abrechnungs-navi.de',hash:'',replace:url=>redirects.push(url)},history:{replaceState:(_,__,url)=>history.push(url)},localStorage:{getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k),key:i=>[...data.keys()][i],get length(){return data.size;}},addEventListener(type,fn){this[type]=fn;},setInterval(fn){this.expiryCheck=fn;},fetch:async(url,opts)=>{fetches.push([url,opts]);return {status:200,json:async()=>({transaction_id:'a'.repeat(32)})};}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../consent.js'),'utf8'),{window:root,URL,Date,console});
  return {root,scripts,fetches,cookies,redirects,history,elements,form,data};
}
(async()=>{
  const first=fixture();check(first.scripts.length===0 && first.fetches.length===0);
  const [banner,settings,reopen]=first.elements;check(!banner.hidden);
  banner.choices[0].listeners.click();check(first.scripts.length===0 && first.fetches.length===0 && banner.hidden);
  reopen.listeners.click();check(settings.open && !settings.querySelector('#an-ads-choice').checked);
  settings.querySelector('#an-ads-choice').checked=true;settings.querySelector('[data-save]').listeners.click();
  check(first.scripts.length===1 && first.scripts[0].src==='https://www.googletagmanager.com/gtag/js?id=AW-12345');
  check(!first.history[0].includes('secret'));const queue=first.root.dataLayer.map(x=>Array.from(x));
  check(queue[0][0]==='consent' && queue[0][1]==='default' && queue[0][2].ad_storage==='denied');
  check(queue.some(x=>x[0]==='config' && x[2].send_page_view===false && x[2].page_referrer==='https://other.invalid/'));
  first.form.listeners.submit();check(first.form.children.ads_consent.value==='yes');
  settings.querySelectorAll('[data-choice]')[0].listeners.click();check(first.redirects[0]==='/');
  check(first.cookies.some(x=>x.startsWith('_gcl_aw=; Max-Age=0')));
  const declined=fixture('/',valid(false));check(declined.scripts.length===0 && declined.fetches.length===0);
  const legal=fixture('/datenschutz.html',valid(true));check(legal.scripts.length===0);
  const thanks=fixture('/danke.html',valid(true));check(thanks.scripts.length===1 && thanks.fetches.length===0);
  thanks.scripts[0].onload();await new Promise(resolve=>setImmediate(resolve));
  check(thanks.fetches.length===1);
  const conversion=thanks.root.dataLayer.map(x=>Array.from(x)).filter(x=>x[0]==='event');
  check(conversion.length===1 && conversion[0][2].transaction_id==='a'.repeat(32));
  check(!JSON.stringify(conversion).includes('secret') && conversion[0][2].value===0);
  thanks.scripts[0].onload();await new Promise(resolve=>setImmediate(resolve));check(thanks.fetches.length===1);
  const direct=fixture('/danke.html',valid(true));direct.root.fetch=async()=>({status:204});direct.scripts[0].onload();await new Promise(resolve=>setImmediate(resolve));check(!direct.root.dataLayer.some(x=>x[0]==='event'));
  const otherTab=fixture('/',valid(true));otherTab.root.storage({key:'an_consent_v1',newValue:valid(false)});check(otherTab.redirects[0]==='/');
  console.log('Consent: '+checks+' privacy and conversion checks passed; all Google calls mocked.');
})().catch(e=>{console.error(e);process.exit(1);});
