(function (root) {
  'use strict';
  const KEY='an_consent_v1', VERSION=1, MAX_AGE=180*86400000;
  function parseChoice(raw, now) {
    try {const c=JSON.parse(raw);return c && c.version===VERSION && typeof c.ads==='boolean' && Number.isFinite(c.at) && c.at<=now && now-c.at<MAX_AGE ? c : null;} catch (_) {return null;}
  }
  function locationForAds(href) {
    const u=new URL(href), clean=new URL(u.origin+u.pathname);
    for(const key of ['gclid','gbraid','wbraid']) {const v=u.searchParams.get(key);if(v && /^[A-Za-z0-9_.~-]{1,256}$/.test(v))clean.searchParams.set(key,v);}
    return clean.href;
  }
  function consentValues(ads) {return {ad_storage:ads?'granted':'denied',ad_user_data:ads?'granted':'denied',ad_personalization:'denied',analytics_storage:'denied'};}
  if(typeof module==='object' && module.exports)module.exports={parseChoice,locationForAds,consentValues};
  if(!root || !root.document)return;
  const doc=root.document, config=root.AN_ADS_CONFIG||{}, trackable=['/','/index.html','/danke.html'].includes(root.location.pathname);
  const configured=config.enabled===true && /^AW-\d+$/.test(config.id||'') && /^[A-Za-z0-9_-]{1,100}$/.test(config.label||'');
  let choice=null, loaded=false, receiptStarted=false;
  try {choice=parseChoice(root.localStorage.getItem(KEY),Date.now());} catch(_) {}
  function allowed(){return !!(choice && choice.ads && Date.now()-choice.at<MAX_AGE);}
  function removeAdsCookies(){
    const host=root.location.hostname;
    try {for(let i=root.localStorage.length-1;i>=0;i--){const key=root.localStorage.key(i);if(/^(_gcl_|_gac_)/.test(key||''))root.localStorage.removeItem(key);}}catch(_){}
    for(const item of doc.cookie.split(';')) {
      const name=item.split('=')[0].trim();if(!/^(_gcl_|_gac_|_gads|_gpi)/.test(name))continue;
      for(const domain of ['',host,'.'+host])doc.cookie=name+'=; Max-Age=0; Path=/; SameSite=Lax'+(domain?'; Domain='+domain:'')+'; Secure';
    }
  }
  function save(ads){
    const wasLoaded=loaded;
    choice={version:VERSION,ads:!!ads,at:Date.now()};
    try {root.localStorage.setItem(KEY,JSON.stringify(choice));}catch(_){}
    banner.hidden=true;settings.close();
    if(!ads){removeAdsCookies();if(wasLoaded){root.location.replace(root.location.pathname);return;}}
    else startAds();
  }
  async function conversion(){
    if(receiptStarted || !allowed() || !configured || root.location.pathname!='/danke.html')return;
    receiptStarted=true;
    try {
      const response=await root.fetch('/tracking/receipt',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'',cache:'no-store'});
      if(response.status!==200 || !allowed())return;
      const data=await response.json();if(!/^[a-f0-9]{32}$/.test(data.transaction_id||''))return;
      root.gtag('event','conversion',{send_to:config.id+'/'+config.label,transaction_id:data.transaction_id,value:0,currency:'EUR',page_location:root.location.origin+'/danke.html',page_referrer:root.location.origin+'/'});
    }catch(_) {/* Inquiry is already accepted; tracking never blocks the customer. */}
  }
  function startAds(){
    if(loaded || !allowed() || !configured || !trackable)return;
    loaded=true;
    // Keep unexpected query content out of both the tag config and the actual address.
    const safe=locationForAds(root.location.href);
    const anchor=['#preise','#preisrechner','#so-gehts','#muster','#fragen','#kontakt','#leistung','#vermieter','#inhalt'].includes(root.location.hash)?root.location.hash:'';
    root.history.replaceState(null,'',safe+anchor);
    root.dataLayer=root.dataLayer||[];
    root.gtag=function(){root.dataLayer.push(arguments);};
    root.gtag('consent','default',consentValues(false));
    root.gtag('set','ads_data_redaction',true);
    root.gtag('set','url_passthrough',false);
    root.gtag('consent','update',consentValues(true));
    root.gtag('js',new Date());
    let ref='';try {ref=doc.referrer?new URL(doc.referrer).origin+'/':'';}catch(_){}
    root.gtag('config',config.id,{send_page_view:false,allow_enhanced_conversions:false,allow_google_signals:false,allow_ad_personalization_signals:false,page_location:locationForAds(root.location.href),page_referrer:ref});
    const script=doc.createElement('script');script.async=true;script.src='https://www.googletagmanager.com/gtag/js?id='+config.id;
    script.onload=function(){if(allowed())conversion();};
    doc.head.appendChild(script);
  }
  const banner=doc.createElement('section');banner.className='an-consent';banner.setAttribute('role','region');banner.setAttribute('aria-label','Datenschutzeinstellungen');banner.hidden=!!choice;
  banner.innerHTML='<h2>Ihre Datenschutzeinstellungen</h2><p>Notwendige Funktionen bleiben immer aktiv. Mit Ihrer Zustimmung verwenden wir Google Ads, um zu messen, ob Anzeigen zu Anfragen führen. Dabei werden unter anderem Ihre IP-Adresse und Klickkennungen verarbeitet; eine Verarbeitung in den USA ist möglich. Ohne Zustimmung laden wir keine Google-Werbetags. Die Website funktioniert auch ohne Zustimmung.</p><p><a href="/datenschutz.html#werbemessung">Details zum Datenschutz</a></p><div class="an-consent-actions"><button type="button" data-choice="false">Ablehnen</button><button type="button" data-settings>Einstellungen</button><button type="button" data-choice="true">Akzeptieren</button></div>';
  const settings=doc.createElement('dialog');settings.className='an-consent-settings';settings.setAttribute('aria-labelledby','an-consent-title');
  settings.innerHTML='<h2 id="an-consent-title">Cookie-Einstellungen</h2><p><label><input type="checkbox" checked disabled> Technisch notwendig</label><br>Wir speichern Ihre Auswahl für bis zu 180 Tage. Geschützte Bereiche verwenden notwendige Sitzungscookies.</p><p><label><input type="checkbox" id="an-ads-choice"> Google Ads zur Erfolgsmessung</label><br>Misst bestätigte Anfragen nach Anzeigenkontakten. Keine Übermittlung von Formularinhalten, Mieterbelegen oder Steuerkennungen. Google Ireland Limited; Verarbeitung in den USA möglich. Keine personalisierte Werbung und kein Google Analytics.</p><p><a href="/datenschutz.html#werbemessung">Anbieter, Daten und Widerruf</a></p><div class="an-consent-actions"><button type="button" data-choice="false">Alles ablehnen</button><button type="button" data-save>Auswahl speichern</button><button type="button" data-close>Schließen</button></div>';
  const reopen=doc.createElement('button');reopen.type='button';reopen.className='an-cookie-settings';reopen.textContent='Cookie-Einstellungen';
  function showSettings(){settings.querySelector('#an-ads-choice').checked=allowed();settings.showModal();}
  for(const el of [banner,settings])for(const button of el.querySelectorAll('[data-choice]'))button.addEventListener('click',()=>save(button.dataset.choice==='true'));
  banner.querySelector('[data-settings]').addEventListener('click',showSettings);
  settings.querySelector('[data-save]').addEventListener('click',()=>save(settings.querySelector('#an-ads-choice').checked));
  settings.querySelector('[data-close]').addEventListener('click',()=>settings.close());
  reopen.addEventListener('click',showSettings);
  doc.body.append(banner,settings,reopen);
  const form=doc.getElementById('anfrage-form');
  if(form)form.addEventListener('submit',()=>{
    let field=form.querySelector('input[name="ads_consent"]');if(!field){field=doc.createElement('input');field.type='hidden';field.name='ads_consent';form.appendChild(field);}
    field.value=allowed() && configured?'yes':'no';
  });
  // Other tabs must stop immediately after withdrawal, too.
  root.addEventListener('storage',event=>{if(event.key!==KEY)return;const previous=allowed();choice=parseChoice(event.newValue,Date.now());banner.hidden=!!choice;if(previous && !allowed()){removeAdsCookies();if(loaded)root.location.replace(root.location.pathname);}else if(allowed())startAds();});
  if(!allowed())removeAdsCookies();
  startAds();
  root.setInterval(()=>{if(loaded && !allowed()){choice=null;removeAdsCookies();root.location.replace(root.location.pathname);}},60000);
})(typeof window==='undefined'?null:window);
