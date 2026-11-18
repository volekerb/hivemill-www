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
    let decision = 'Await both checks';
    let explanation = 'Both the reviewer and QA still need to record a verdict on this change.';
    if (review === 'fail' || qa === 'fail') {
      decision = 'Return to the coder';
      explanation = 'A failed verdict sends the change back with findings. The revised commit needs fresh review and QA.';
    } else if (review === 'pass' && qa === 'pass') {
      decision = 'Eligible for merge';
      explanation = 'With both verdicts on the current revision, the judge can merge once the required CI checks pass and the branch is mergeable.';
    } else if (review === 'pass') {
      decision = 'Await QA';
      explanation = 'The reviewer passed. The judge waits for a QA verdict on the same revision.';
    } else if (qa === 'pass') {
      decision = 'Await review';
      explanation = 'QA passed. The judge waits for a reviewer verdict on the same revision.';
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
