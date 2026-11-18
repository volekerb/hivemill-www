// Progressive enhancement: all stories remain readable without JavaScript.
const stages = [
 ['You + the boss', 'Start with a clear outcome.', 'Describe the change and how you will know it works. The boss turns that request into a goal with acceptance criteria.'],
 ['Director + lead', 'Give every agent a clear job.', 'A director staffs a lead. The lead plans tasks and assigns work, so each agent has a defined responsibility.'],
 ['Coder', 'Build the change in its own branch.', 'A coder implements the task in a dedicated worktree and opens a pull request. The coder cannot approve or merge its own change.'],
 ['Reviewer + QA', 'Check the code. Run the tests.', 'One agent reviews the diff. Another runs tests against the acceptance criteria. Their verdicts are separate and recorded.'],
 ['Judge', 'Merge only when both checks pass.', 'The judge evaluates the reviewer and QA verdicts. Both must pass to merge. A failure returns to the coder with findings.']
];
const stageButtons = [...document.querySelectorAll('[data-stage]')];
const play = document.getElementById('play-flow');
let stage = 0;
let timer;
const reduce = matchMedia('(prefers-reduced-motion: reduce)');
function stopSequence() { clearTimeout(timer); timer = undefined; if (play) play.textContent = reduce.matches ? 'Next checkpoint →' : 'Play the sequence →'; }
function selectStage(index) {
 stage = index;
 const process = document.querySelector(".factory-process"); if (process) process.dataset.activeStage = String(index);
 stageButtons.forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.stage) === index)));
 ['stage-role','stage-title','stage-copy'].forEach((id,i) => { const node = document.getElementById(id); if (node) node.textContent = stages[index][i]; });
}
stageButtons.forEach(b => b.addEventListener('click', () => { stopSequence(); selectStage(Number(b.dataset.stage)); }));
if (play) {
 play.hidden = false;
 stopSequence();
 play.addEventListener('click', () => {
  if (timer) { stopSequence(); return; }
  if (reduce.matches) { selectStage((stage + 1) % stages.length); return; }
  selectStage(0);
  play.textContent = 'Pause the sequence';
  const next = () => { if (stage === stages.length - 1) { stopSequence(); return; } selectStage(stage + 1); timer = setTimeout(next, 2600); };
  timer = setTimeout(next, 2600);
 });
}
reduce.addEventListener('change', stopSequence);
document.addEventListener('visibilitychange', () => { if (document.hidden) stopSequence(); });
const storyButtons = [...document.querySelectorAll('[data-story]')];
const stories = [...document.querySelectorAll('[data-story-panel]')];
function selectStory(name) {
 storyButtons.forEach(b => b.setAttribute('aria-pressed', String(b.dataset.story === name)));
 stories.forEach(p => { p.hidden = p.dataset.storyPanel !== name; p.classList.toggle('is-entering', !p.hidden); });
}
if (stories.length) { selectStory('saas'); storyButtons.forEach(b => b.addEventListener('click', () => selectStory(b.dataset.story))); }
// An explicit theme control makes the design accessible in either appearance.
const header = document.querySelector('header.site .wrap');
if (header) {
 const themeButton = document.createElement('button');
 themeButton.type = 'button'; themeButton.className = 'theme-toggle';
 const system = matchMedia('(prefers-color-scheme: dark)');
 try { const saved = localStorage.getItem('hivemill-site-theme'); if (saved === 'dark' || saved === 'light') document.documentElement.dataset.theme = saved; } catch { /* Theme still works when storage is blocked. */ }
 const isDark = () => document.documentElement.dataset.theme ? document.documentElement.dataset.theme === 'dark' : system.matches;
 const themeSources = [...document.querySelectorAll('picture source[media]')].filter(s => s.media.includes('prefers-color-scheme: dark'));
 themeSources.forEach(s => { s.dataset.originalMedia = s.media; });
 const sync = () => {
  themeButton.textContent = isDark() ? 'Light' : 'Dark';
  themeButton.setAttribute('aria-label', `Switch to ${isDark() ? 'light' : 'dark'} appearance`);
  themeSources.forEach(s => { s.media = document.documentElement.dataset.theme ? s.dataset.originalMedia.replace('(prefers-color-scheme: dark)', isDark() ? '(min-width: 0px)' : '(min-width: 999999px)') : s.dataset.originalMedia; });
 };
 themeButton.addEventListener('click', () => { document.documentElement.dataset.theme = isDark() ? 'light' : 'dark'; try { localStorage.setItem('hivemill-site-theme', document.documentElement.dataset.theme); } catch { /* Current-page preference still applies. */ } sync(); });
 system.addEventListener('change', sync); sync(); header.append(themeButton);
}

// One physical factory shot; pause offscreen, on hidden tabs and for reduced motion.
const heroFilm = document.querySelector('.hero-film');
const motionToggle = document.querySelector('.motion-toggle');
if (heroFilm && motionToggle) {
 let visible = true;
 let pausedByVisitor = false;
 const motionSync = () => {
  if (reduce.matches || document.hidden || !visible || pausedByVisitor) { heroFilm.pause(); return; }
  if (!heroFilm.src) heroFilm.src = heroFilm.dataset.motionSrc;
  heroFilm.play().then(() => { motionToggle.hidden = false; motionToggle.textContent = 'Pause motion Ⅱ'; motionToggle.setAttribute('aria-label','Pause factory animation'); }).catch(() => { motionToggle.hidden = false; motionToggle.textContent = 'Play motion ▷'; motionToggle.setAttribute('aria-label','Play factory animation'); });
 };
 motionToggle.addEventListener('click', () => {
  pausedByVisitor = !heroFilm.paused;
  if (pausedByVisitor) { heroFilm.pause(); motionToggle.textContent='Play motion ▷'; motionToggle.setAttribute('aria-label','Play factory animation'); }
  else { if (!heroFilm.src) heroFilm.src=heroFilm.dataset.motionSrc; heroFilm.play().then(()=>{ motionToggle.textContent='Pause motion Ⅱ'; motionToggle.setAttribute('aria-label','Pause factory animation'); }).catch(()=>{}); }
 });
 new IntersectionObserver(entries => { visible=entries[0].isIntersecting; motionSync(); },{threshold:.05}).observe(heroFilm);
 reduce.addEventListener('change',motionSync); document.addEventListener('visibilitychange',motionSync);
}
// Render the actual product, with browser-sharp type at any display density.
const productFrame = document.querySelector('.console-viewport iframe');
if (productFrame) {
 const viewport = productFrame.parentElement;
 const buttons = [...document.querySelectorAll('[data-product-view]')];
 const openProduct = document.getElementById('open-product');
 const caption = document.getElementById('product-view-caption');
 const interact = document.getElementById('interact-product');
 const captions = {'index.html':'Goals, active agents and the decisions that need you.','tasks.html':'Task states, assigned agents and the pull requests behind the work.','resources.html':'Capacity, usage limits and the checks that govern agent starts.','tokens.html':'Claude token estimates and Cursor activity. Estimates are not invoices.'};
 const finish = () => { viewport.classList.remove('is-interactive'); productFrame.tabIndex=-1; interact.textContent='Interact with demo ↗'; };
 const loadView = (path) => { viewport.setAttribute('aria-busy','true'); finish(); productFrame.src='demo/'+path; };
 productFrame.addEventListener('load',()=>{ viewport.setAttribute('aria-busy','false'); });
 buttons.forEach(button=>button.addEventListener('click',()=>{
  const path=button.dataset.productView;
  buttons.forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
  caption.textContent=captions[path]; openProduct.href='demo/'+path;
  productFrame.title='Hivemill product preview: '+button.textContent+'. Fictional demo data.';
  loadView(path);
 }));
 interact.hidden=false;
 interact.addEventListener('click',()=>{
  if(viewport.classList.contains('is-interactive')) { finish(); return; }
  viewport.classList.add('is-interactive'); productFrame.tabIndex=0; interact.textContent='Finish exploring ×';
 });
 const observer=new IntersectionObserver(entries=>{if(entries[0].isIntersecting){ if(!productFrame.src) productFrame.src=productFrame.dataset.src; observer.disconnect(); }},{rootMargin:'400px'});
 observer.observe(viewport);
}
// Film chapters are direct, keyboard-operable ways to inspect the walkthrough.
const filmPlayer=document.querySelector('.film-player');
if(filmPlayer) {
 let requestedChapter=null;
 filmPlayer.addEventListener('loadedmetadata',()=>{if(requestedChapter!==null){filmPlayer.currentTime=requestedChapter;requestedChapter=null;}});
 document.querySelectorAll('[data-film-time]').forEach(button=>button.addEventListener('click',()=>{
  const time=Number(button.dataset.filmTime);
  if(filmPlayer.readyState>=1) filmPlayer.currentTime=time;
  else { requestedChapter=time; filmPlayer.load(); }
  filmPlayer.play().catch(()=>{});
 }));
}
// Keep an embedded preview inside the demo and match the surrounding appearance.
if (productFrame) {
 const syncProductTheme = () => {
  try {
   const doc=productFrame.contentDocument;
   if(!doc?.documentElement) return;
   doc.documentElement.dataset.embedded="true";
   const appearance=document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
   doc.documentElement.dataset.theme=appearance;
   doc.querySelectorAll('[data-mode]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.mode===appearance)));
  } catch { /* The open-demo link remains available if embedding is unavailable. */ }
 };
 productFrame.addEventListener('load',()=>{
  syncProductTheme();
  try { productFrame.contentDocument.querySelectorAll('a[href="../"]').forEach(link=>link.target='_top'); } catch { /* Same-origin preview normally permits this. */ }
 });
 new MutationObserver(syncProductTheme).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
 matchMedia('(prefers-color-scheme:dark)').addEventListener('change',syncProductTheme);
}
// Product captures can be inspected at their original density, without altering the UI.
const inspectableFigures=[...document.querySelectorAll('figure')].filter(figure=>figure.querySelector('picture img'));
if(inspectableFigures.length && typeof HTMLDialogElement!=='undefined') {
 const dialog=document.createElement('dialog'); dialog.className='product-lightbox';
 const close=document.createElement('button'); close.type='button'; close.className='lightbox-close'; close.textContent='Close ×'; close.setAttribute('aria-label','Close product image');
 const image=document.createElement('img');
 const caption=document.createElement('p'); caption.id='product-lightbox-caption';
 dialog.setAttribute('aria-label','Product image'); dialog.setAttribute('aria-describedby',caption.id);
 dialog.append(close,image,caption);document.body.append(dialog);
 close.addEventListener('click',()=>dialog.close());
 dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
 inspectableFigures.forEach(figure=>{
  const original=figure.querySelector('picture img');
  const control=document.createElement('button');control.type='button';control.className='inspect-image';control.textContent='Inspect image ↗';control.setAttribute('aria-label','Inspect product image: '+original.alt);
  control.addEventListener('click',()=>{
   const current=original.currentSrc||original.src;
   image.src=current.includes('-1x.')&&!current.includes('herdr-')?current.replace('-1x.','-2x.'):current;
   image.alt=original.alt; caption.textContent=figure.querySelector('figcaption')?.textContent||'Actual product interface. Demo data.';
   dialog.showModal();
  });
  figure.append(control);
 });
}
