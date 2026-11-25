// Keep each in-page contents link usable with ordinary anchor navigation.
const contents = document.querySelector('.ed-toc');
if (contents) {
  const entries = [...contents.querySelectorAll('a[href^="#"]')].map(link => ({
    link,
    section: document.querySelector(link.hash)
  })).filter(entry => entry.section);

  function markSection() {
    const header = document.querySelector('header.site');
    const sticky = header && getComputedStyle(header).position === 'sticky';
    const threshold = (sticky ? header.getBoundingClientRect().bottom : 0) + 100;
    let current = entries[0];
    for (const entry of entries) {
      if (entry.section.getBoundingClientRect().top <= threshold) current = entry;
    }
    for (const entry of entries) {
      if (entry === current) entry.link.setAttribute('aria-current', 'location');
      else entry.link.removeAttribute('aria-current');
    }
  }

  let frame;
  function scheduleSectionUpdate() {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = undefined;
      markSection();
    });
  }

  markSection();
  const sectionObserver = new IntersectionObserver(scheduleSectionUpdate, { rootMargin: '-96px 0px -65% 0px', threshold: 0 });
  entries.forEach(entry => sectionObserver.observe(entry.section));
  addEventListener('hashchange', scheduleSectionUpdate);
  addEventListener('resize', scheduleSectionUpdate);
}

const gate = document.querySelector('.ed-gate');
if (gate) {
  const controls = gate.querySelector('form');
  const result = gate.querySelector('.ed-gate-result');
  const title = result.querySelector('h3');
  const reason = result.querySelector('[data-gate-reason]');
  const fallback = gate.querySelector('.ed-gate-static');

  function updateVerdict() {
    const review = controls.elements.review.value;
    const qa = controls.elements.qa.value;
    let decision = 'Await CI';
    let explanation = 'The judge starts only after CI is green on the current head.';
    if (review === 'fail' || qa === 'fail') {
      decision = 'Back to the task session';
      explanation = 'Red CI or a judge REJECT goes back to the same session with the reasons. After the round cap, the task goes to you.';
    } else if (review === 'pass' && qa === 'pass') {
      decision = 'Runner merges';
      explanation = 'With a judge MERGE on this exact head and green checks, the runner merges with --match-head-commit.';
    } else if (review === 'pass') {
      decision = 'Await the judge';
      explanation = 'CI is green. A fresh judge reads the packet.';
    } else if (qa === 'pass') {
      decision = 'Await CI';
      explanation = 'The judge starts only after CI is green, so a merge verdict cannot come first.';
    }
    title.textContent = decision;
    reason.textContent = explanation;
  }

  updateVerdict();
  fallback.hidden = true;
  controls.hidden = false;
  result.hidden = false;
  controls.addEventListener('change', () => {
    updateVerdict();
    result.classList.add('is-updated');
  });
  result.addEventListener('animationend', () => result.classList.remove('is-updated'));
}
