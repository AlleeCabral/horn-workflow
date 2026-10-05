/* hornflow app shell.
 *
 * Additive only: the viewer's own markup and script are untouched. This file
 * does two things:
 *   1. renders the Workflow / Results panes from the embedded app_view model
 *      (read-only - it never computes or decides anything);
 *   2. adds the Dimensions overlay to the existing 3D view.
 *
 * If the app_view model is absent or empty, every tab except Viewer is removed
 * and the page behaves exactly like the original viewer.
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------- helpers
  function h(tag, attrs, kids) {
    var e = document.createElement(tag);
    if (attrs) {
      for (var k in attrs) {
        if (k === 'class') e.className = attrs[k];
        else if (k === 'text') e.textContent = attrs[k];
        else e.setAttribute(k, attrs[k]);
      }
    }
    (kids || []).forEach(function (c) {
      if (c === null || c === undefined) return;
      e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return e;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function fmt(v, digits) {
    if (v === null || v === undefined || v === '') return '\u2014';
    return (typeof v === 'number') ? v.toFixed(digits === undefined ? 2 : digits) : String(v);
  }
  function copyText(text, btn) {
    function done() {
      if (!btn) return;
      var old = btn.textContent;
      btn.textContent = 'Copied';
      setTimeout(function () { btn.textContent = old; }, 1200);
    }
    function fallback() {
      var ta = h('textarea', { style: 'position:fixed;top:-1000px' });
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } catch (e) { /* nothing else to do */ }
      document.body.removeChild(ta);
      done();
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, fallback);
      return;
    }
    fallback();
  }
  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) { /* private mode: degrade silently */ }
    return null;
  }
  function band(title, chip) {
    var body = h('div', { class: 'body' });
    var head = h('header', {}, [h('h2', { text: title })]);
    if (chip) head.appendChild(h('span', { class: 'chip ' + (chip.cls || '') + ' kick',
                                           text: chip.text }));
    var wrap = h('div', { class: 'wf-band' + (chip && chip.cls === 'locked' ? ' locked' : '') },
                 [head, body]);
    return { root: wrap, body: body, head: head };
  }
  function copyBtn(label, text) {
    var b = h('button', { class: 'btn' }, [label]);
    b.addEventListener('click', function () { copyText(text, b); });
    return b;
  }
  function todoBtn(label, why) {
    var b = h('button', { class: 'btn', disabled: 'disabled' }, [label]);
    b.title = why || 'Available once the local host (M4) is running.';
    return b;
  }
  function log(msg) { if (window.console) window.console.log('[hornflow-app] ' + msg); }

  // ---------------------------------------------------------------- live host
  // With no server (a file:// snapshot) every one of these is a no-op, so the
  // page degrades to exactly the read-only view it always was.
  var live = {
    on: false,          // the local host answered GET /api/view
    dirty: {},          // field key -> value typed but not saved
    poll: null,
    lastState: null,
  };

  function post(path, body) {
    return fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) {
          var err = (j && j.error) || {};
          var extra = err.field_errors
            ? ' (' + Object.keys(err.field_errors).join(', ') + ')' : '';
          throw new Error((err.message || ('HTTP ' + r.status)) + extra);
        }
        return j;
      });
    });
  }

  function note(msg, cls) {
    var bar = document.getElementById('app-note');
    if (!bar) {
      bar = h('div', { class: 'app-note', id: 'app-note' });
      var host = document.getElementById('tabs');
      if (host && host.parentNode) { host.parentNode.insertBefore(bar, host.nextSibling); }
    }
    bar.className = 'app-note' + (cls ? ' ' + cls : '');
    bar.textContent = msg || '';
    bar.hidden = !msg;
  }

  function dirtyCount() { return Object.keys(live.dirty).length; }

  function refreshActions() {
    // Re-render only the summary band: cheap, and it cannot disturb a form field
    // the user is typing into elsewhere on the page.
    var pane = document.getElementById('pane-workflow');
    if (!pane || !pane.firstChild) return;
    pane.replaceChild(summaryBand(), pane.firstChild);
  }

  function setField(key, raw, isNumber) {
    if (raw === '' || raw === null || raw === undefined) {
      delete live.dirty[key];
    } else {
      live.dirty[key] = isNumber ? Number(raw) : raw;
    }
    refreshActions();
  }

  // ---------------------------------------------------------------- boot
  var tabButtons = Array.prototype.slice.call(document.querySelectorAll('#tabs .tab'));
  var node = document.getElementById('app_view');
  var raw = node ? node.textContent.trim() : '';
  if (!raw) { viewerOnly(); return; }

  var view;
  try { view = JSON.parse(raw); } catch (e) { viewerOnly(); return; }
  if (!view || !view.view_schema) { viewerOnly(); return; }

  function activate(name) {
    tabButtons.forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-pane') === name);
    });
    ['viewer', 'workflow', 'results'].forEach(function (p) {
      var pane = document.getElementById('pane-' + p);
      if (pane) pane.classList.toggle('inactive', p !== name);
    });
    // Inactive panes keep their layout (visibility, not display), so nothing
    // needs re-measuring - a nudge keeps the canvas-backed pane honest anyway.
    window.dispatchEvent(new Event('resize'));
  }

  function viewerOnly() {
    tabButtons.forEach(function (b) {
      if (b.getAttribute('data-pane') !== 'viewer') b.parentNode.removeChild(b);
    });
    activate('viewer');
  }

  tabButtons.forEach(function (b) {
    b.addEventListener('click', function () {
      var name = b.getAttribute('data-pane');
      store('hornflow.tab', name);
      activate(name);
    });
  });

  function defaultTab() {
    var q = /[?&]tab=([a-z]+)/i.exec(window.location.search);
    if (q && ['viewer', 'workflow', 'results'].indexOf(q[1]) >= 0) return q[1];
    var saved = store('hornflow.tab');
    if (saved && ['viewer', 'workflow', 'results'].indexOf(saved) >= 0) return saved;
    // decision: a first run opens on Workflow (the questions are the point);
    // an existing run opens on the geometry.
    return view.mode === 'first_run' ? 'workflow' : 'viewer';
  }

  function bemChipClass(state) {
    if (state === 'BEM_VALIDATED' || state === 'validated') return 'validated';
    if (state === 'BEM_REJECTED' || state === 'rejected') return 'rejected';
    if (state === 'GUI_REQUIRED' || state === 'MANUAL_SOLVE_PENDING' ||
        state === 'MANUAL_SOLVE_COMPLETED') return 'running';
    if (state === 'failed' || state === 'blocked') return 'failed';
    return '';
  }

  // ---------------------------------------------------------------- strip
  function renderStrip() {
    var strip = document.getElementById('strip');
    if (!strip) return;
    clear(strip);
    var cs = view.current_state || {};
    var run = view.run ? view.run.run_id : 'no run yet';
    [
      h('span', { text: (view.project && view.project.name) || '(unnamed)' }),
      h('span', { class: 'sep', text: '\u00b7' }),
      h('span', { text: run }),
      h('span', { class: 'sep', text: '\u00b7' }),
      h('span', { class: 'chip ' + bemChipClass(cs.bem_state || view.mode),
                  text: cs.bem_state || view.mode }),
      h('span', { class: 'sep', text: '\u00b7' }),
      h('span', { class: 'next',
                  text: 'next: ' + ((view.next_action && view.next_action.label) || '\u2014') }),
      h('span', { class: 'sep', text: '\u00b7' }),
      h('span', { class: 'opt', text: 'assumptions: ' + (cs.assumptions || 0) })
    ].forEach(function (b) { strip.appendChild(b); });
  }


  // ---------------------------------------------------------------- summary
  // The persistent top summary.  Everything here is read from current_state,
  // next_action, completion and brief_actions - the browser adds nothing.
  function gateMark(g) {
    return g.status === 'passed' ? '\u2713'
      : g.status === 'skipped' ? '\u2013'
      : (g.status === 'failed' || g.status === 'blocked') ? '\u2717'
      : g.status === 'running' ? '\u22ef' : '\u25cb';
  }

  function gateCls(g) {
    return g.status === 'passed' ? 'passed'
      : (g.status === 'failed' || g.status === 'blocked') ? 'failed'
      : g.status === 'skipped' ? 'optional' : '';
  }

  function gateRow(g) {
    var item = h('div', { class: 'gate' }, [
      h('span', { class: 'chip ' + gateCls(g), text: gateMark(g),
                  'aria-hidden': 'true' }),
      h('span', { class: 'nm', text: g.stage + (g.optional ? ' (optional)' : '') }),
      h('span', { class: 'st muted', text: g.status })
    ]);
    var tip = [g.detail, (g.blocked_by && g.blocked_by.length)
      ? 'blocked by: ' + g.blocked_by.join(', ') : ''].filter(Boolean).join(' | ');
    if (tip) { item.title = tip; }
    return item;
  }

  function summaryBand() {
    var cs = view.current_state || {};
    var na = view.next_action || {};
    var comp = view.completion || {};
    var act = view.brief_actions || {};
    var b = band('Current state',
                 { text: cs.bem_state || view.mode,
                   cls: bemChipClass(cs.bem_state || view.mode) });

    var kv = h('dl', { class: 'kv kv-summary' });
    function row(k, v) {
      kv.appendChild(h('dt', { text: k }));
      kv.appendChild(h('dd', {}, [String(v)]));
    }
    row('project', (view.project && view.project.name) || '(unnamed)');
    row('run', (view.run && view.run.run_id) || 'no run yet');
    row('current stage', cs.current_stage
      ? (cs.current_stage.order + 1) + ' of ' + cs.stages_total_workflow
        + ' \u00b7 ' + cs.current_stage.name
      : '\u2014 all stages complete');
    row('brief revision', fmt(cs.brief_revision, 0));
    row('input hash', cs.input_hash
      ? String(cs.input_hash).slice(0, 24) + '\u2026' : '\u2014');
    row('required answers', (comp.required_fields_answered || 0) + ' of '
        + (comp.required_fields_total || 0)
        + '  (' + (comp.blocker_count || 0) + ' blocking)');
    row('validation warnings', String(cs.warnings || 0));
    row('BEM state', (cs.bem_state || '\u2014')
        + (cs.bem_status ? ' (' + cs.bem_status + ')' : ''));
    b.body.appendChild(kv);

    // exactly one primary action, visually obvious
    var primary = h('div', { class: 'primary-action' });
    primary.appendChild(h('div', { class: 'pa-label', text: na.label || 'nothing to do' }));
    if (na.why) { primary.appendChild(h('div', { class: 'pa-why', text: na.why })); }
    primary.appendChild(h('div', { class: 'pa-owner muted',
                                   text: 'owner: ' + (na.owner || '\u2014') }));
    var cta = na.cta || {};
    if (cta.kind === 'copy_command' && cta.value) {
      primary.appendChild(h('div', { class: 'pa-row' }, [copyBtn('Copy command', cta.value)]));
      primary.appendChild(h('pre', { class: 'cmd', text: cta.value }));
    } else if (cta.kind === 'open_url' && cta.value) {
      primary.appendChild(h('div', { class: 'pa-row' }, [
        h('a', { class: 'btn', href: cta.value, target: '_blank', rel: 'noopener' }, ['Open'])
      ]));
    } else {
      primary.appendChild(h('div', { class: 'pa-row' }, [todoBtn(
        na.label || 'action',
        'This action mutates state; it arrives with the local host (M4).')]));
    }
    if (na.blockers && na.blockers.length) {
      primary.appendChild(h('div', { class: 'muted',
        text: 'blocked by: ' + na.blockers.join(', ') }));
    }
    b.body.appendChild(primary);

    // the brief actions.  In the local host they really run; in the snapshot they
    // explain why they cannot.
    var dirty = dirtyCount();
    var acts = h('div', { class: 'brief-actions' });
    function actionBtn(label, enabled, why, run, primary) {
      var attrs = { class: 'btn' + (primary ? ' primary' : ''), type: 'button',
                    title: why || '', text: label };
      if (!enabled) { attrs.disabled = 'disabled'; }
      var btn = h('button', attrs);
      if (enabled) { btn.addEventListener('click', run); }
      acts.appendChild(h('div', { class: 'ba' }, [
        btn, h('div', { class: 'ba-why muted',
                        text: (enabled ? 'Enabled \u2014 ' : 'Disabled \u2014 ') + (why || '') })
      ]));
      return btn;
    }
    var canSave = live.on && dirty > 0;
    var canFreeze = live.on && (act.freeze_brief || {}).enabled && dirty === 0;
    var saveWhy = live.on ? (dirty
      ? dirty + ' edited value' + (dirty === 1 ? '' : 's') + ' not saved yet.'
      : (act.save_draft || {}).reason) : (act.save_draft || {}).reason;
    var freezeWhy = live.on ? (dirty
      ? 'Save the draft first - ' + dirty + ' edited value'
        + (dirty === 1 ? '' : 's') + '.'
      : (act.freeze_brief || {}).reason) : (act.freeze_brief || {}).reason;

    actionBtn('Save draft', canSave, saveWhy, function () {
      post('/api/brief', { values: live.dirty }).then(function (out) {
        live.dirty = {};
        applyView(out.view);
        note((out.warnings || []).join(' ') || 'Draft saved.',
             (out.warnings || []).length ? 'warn' : 'ok');
      }).catch(function (e) { note('Save failed: ' + e.message, 'bad'); });
    });
    actionBtn('Freeze brief', canFreeze, freezeWhy, function () {
      post('/api/brief/freeze', { values: currentValues() }).then(function (out) {
        live.dirty = {};
        applyView(out.view);
        note(out.ok
          ? 'Brief frozen: revision ' + out.revision + ' \u2192 ' + out.definition
            + ((out.warnings || []).length ? '  |  ' + out.warnings.join(' ') : '')
          : 'Freeze refused: ' + JSON.stringify(out.field_errors || {}),
          out.ok ? ((out.warnings || []).length ? 'warn' : 'ok') : 'bad');
      }).catch(function (e) { note('Freeze failed: ' + e.message, 'bad'); });
    }, true);
    b.body.appendChild(acts);
    b.body.appendChild(runBox());
    return b.root;
  }

  // ------------------------------------------------------------ run + BEM loop
  function currentValues() {
    var out = {};
    (view.questions || []).forEach(function (q) {
      (q.fields || []).forEach(function (f) {
        if (f.accepted) { out[f.key] = f.value; }
      });
    });
    for (var k in live.dirty) { out[k] = live.dirty[k]; }
    return out;
  }

  function runBox() {
    var lv = view.live || {};
    var box = h('div', { class: 'run-box' });
    var frozen = (view.brief_draft || {}).definition;
    var state = lv.state || 'idle';
    var cls = state === 'failed' ? 'failed' : state === 'done' ? 'passed'
      : state === 'running' ? 'running' : '';

    var row = h('div', { class: 'run-row' }, [
      h('span', { class: 'chip ' + cls, text: state })
    ]);
    if (lv.stage) { row.appendChild(h('span', { class: 'muted', text: '\u00b7 ' + lv.stage })); }
    if (lv.definition) {
      row.appendChild(h('span', { class: 'muted kick', text: lv.definition }));
    }
    box.appendChild(row);

    if (live.on && lv.stages_total) {
      var bar = h('div', { class: 'pbar', role: 'progressbar',
                           'aria-valuenow': String(lv.percent || 0),
                           'aria-valuemin': '0', 'aria-valuemax': '100' });
      bar.appendChild(h('div', { class: 'pfill',
                                 style: 'width:' + (lv.percent || 0) + '%' }));
      box.appendChild(bar);
      box.appendChild(h('div', { class: 'muted',
        text: (lv.stages_passed || 0) + ' of ' + lv.stages_total + ' stages passed'
              + '  (' + (lv.percent || 0) + '%)' }));
    }
    if (lv.error) {
      box.appendChild(h('div', { class: 'locked-why failed', text: lv.error }));
    }
    var tail = (lv.messages || []).slice(-6);
    if (live.on && tail.length) {
      box.appendChild(h('pre', { class: 'cmd', text: tail.join('\n') }));
    }

    if (!live.on) {
      box.appendChild(h('div', { class: 'placeholder',
        text: 'Read-only snapshot - there is no server to act on. Start the local '
              + 'host:  python3 -m hornflow.app --run-dir <run dir>' }));
      return box;
    }

    var btns = h('div', { class: 'run-btns' });
    var canRun = !!frozen && state !== 'running';
    var why = !frozen ? 'Freeze a brief first - a run needs a definition file.'
      : state === 'running' ? 'A run is already in flight.'
      : 'Starts a new, immutable run from the frozen definition.';
    var run = h('button', { class: 'btn primary', type: 'button', title: why,
                            text: 'Start run' });
    if (!canRun) { run.setAttribute('disabled', 'disabled'); }
    run.addEventListener('click', function () {
      note('Run started\u2026', 'ok');
      post('/api/run', {}).then(function () {
        poll(true);
      }).catch(function (e) { note('Run failed to start: ' + e.message, 'bad'); });
    });
    btns.appendChild(run);

    if ((view.manual_bem || {}).available) {
      var imp = h('button', { class: 'btn', type: 'button',
                              text: 'Import & validate (.vips)',
                              title: 'Validates the exported .vips spectra and '
                                     + 'compares them with the 1-D reference.' });
      imp.addEventListener('click', function () {
        post('/api/import', {}).then(function (out) {
          applyView(out.view);
          note(out.ok ? 'Imported and compared: BEM_VALIDATED'
                      : 'Imported: BEM_REJECTED - the difference is over tolerance',
               out.ok ? 'ok' : 'warn');
        }).catch(function (e) { note('Import failed: ' + e.message, 'bad'); });
      });
      btns.appendChild(imp);
    }

    if ((view.outcome || {}).verdict === 'BEM_REJECTED') {
      var sel = h('select', { class: 'finput', id: 'acc-reason',
                              'aria-label': 'reason for accepting unvalidated' });
      (view.accept_reasons || []).forEach(function (r) {
        sel.appendChild(h('option', { value: r }, [r]));
      });
      var acc = h('button', { class: 'btn', type: 'button',
                              text: 'Accept as unvalidated',
                              title: 'Records a decision. It does NOT validate the '
                                     + 'acoustic result.' });
      acc.addEventListener('click', function () {
        post('/api/decision', { kind: 'accept_unvalidated', reason: sel.value })
          .then(function (out) {
            applyView(out.view);
            note('Decision recorded. The acoustic result stays unvalidated.', 'warn');
          }).catch(function (e) { note('Decision failed: ' + e.message, 'bad'); });
      });
      btns.appendChild(sel);
      btns.appendChild(acc);
    }
    box.appendChild(btns);
    box.appendChild(h('div', { class: 'muted', style: 'margin-top:4px',
      text: 'Start run calls the pipeline in this process - no shell, and no command '
            + 'built from the page.' }));
    return box;
  }

  // Everything below is READ FROM view.completion / view.questions.  The browser
  // never decides whether a group or a wave is complete - that arithmetic lives
  // in hornflow/app/view.py (the old renderer computed it here, which is how W4
  // could say "wave A complete" while required values were blank).
  function fieldRow(f) {
    var isSet = f.accepted === true;
    var val = isSet ? (fmt(f.value, 3) + (f.unit ? ' ' + f.unit : ''))
                    : (f.required ? 'Required' : 'Optional');
    var wrap = h('div', { class: 'field' + (f.required && !isSet ? ' needs' : '') });
    var current = live.on && (f.key in live.dirty) ? live.dirty[f.key] : f.value;

    if (live.on) {
      // one clear control per field; the unit is shown once, after the value
      var attrs = { class: 'finput', name: f.key, id: 'f-' + f.key,
                    'aria-label': f.label };
      var control;
      if (f.enum) {
        control = h('select', attrs);
        if (!f.required) { control.appendChild(h('option', { value: '' }, ['(none)'])); }
        f.enum.forEach(function (opt) {
          var o = h('option', { value: opt }, [opt]);
          if (String(current) === opt) { o.selected = true; }
          control.appendChild(o);
        });
        if (f.required && current === null) { control.selectedIndex = -1; }
      } else {
        attrs.type = (f.type === 'number') ? 'number' : 'text';
        attrs.step = 'any';
        attrs.value = (current === null || current === undefined) ? '' : current;
        if (f.required) { attrs.required = 'required'; }
        control = h('input', attrs);
      }
      control.addEventListener('change', function () {
        setField(f.key, control.value, f.type === 'number');
      });
      wrap.appendChild(h('div', { class: 'fline' }, [
        h('label', { class: 'fl', for: 'f-' + f.key, text: f.label,
                     title: f.key + (f.help ? ' \u2014 ' + f.help : '') }),
        control,
        f.unit ? h('span', { class: 'funit muted', text: f.unit }) : null
      ]));
    } else {
      wrap.appendChild(h('div', { class: 'fline' }, [
        h('span', { class: 'fl', text: f.label,
                    title: f.key + (f.help ? ' \u2014 ' + f.help : '') }),
        h('span', { class: 'fv' + (isSet ? '' : ' unknown'), text: val })
      ]));
    }

    var meta = [f.required ? 'required' : 'optional'];
    if (isSet) { meta.push('answered'); }
    if (f.provenance) { meta.push(String(f.provenance).toLowerCase()); }
    if (f.source) { meta.push('from ' + String(f.source).replace('_', ' ')); }
    if (f.enum && !live.on) { meta.push('one of: ' + f.enum.join(' / ')); }
    wrap.appendChild(h('div', { class: 'fmeta muted', text: meta.join(' \u00b7 ') }));
    if (f.help && !isSet) {
      wrap.appendChild(h('div', { class: 'fhelp muted', text: f.help }));
    }
    return wrap;
  }

  // ---------------------------------------------------------------- questions
  // One node per question group.  Render only - completion comes from the model.
  function questionGroup(q) {
    var box = h('div', { class: 'q' });
    box.appendChild(h('div', { class: 'qhead' }, [
      h('span', { class: 'pr', text: q.prompt }),
      h('span', { class: 'chip ' + (q.complete ? 'passed' : 'attention') + ' kick',
                  text: q.required_answered + '/' + q.required_total + ' required' })
    ]));
    if (q.why) { box.appendChild(h('div', { class: 'why', text: q.why })); }
    var fields = h('div', { class: 'fields' });
    (q.fields || []).forEach(function (f) { fields.appendChild(fieldRow(f)); });
    box.appendChild(fields);
    return box;
  }

  function questionGroups(ids) {
    var want = ids || [];
    return (view.questions || []).filter(function (q) {
      return want.indexOf(q.id) >= 0;
    }).map(questionGroup);
  }

  // ---------------------------------------------------------------- accordion
  function stageChipCls(s) {
    return s === 'complete' ? 'passed'
      : (s === 'blocked' || s === 'failed') ? 'failed'
      : s === 'needs_input' ? 'attention'
      : s === 'locked' ? 'locked' : 'running';
  }

  function stageStatusWord(s) {
    return s === 'needs_input' ? 'needs input'
      : s === 'in_progress' ? 'in progress'
      : (s || 'pending');
  }

  function stageBodyContent(stage) {
    var frag = document.createDocumentFragment();
    if (stage.locked) {
      frag.appendChild(h('div', { class: 'locked-why' }, [
        h('strong', { text: 'Locked \u2014 ' }),
        h('span', { text: stage.locked_reason || 'an earlier stage is unfinished.' })
      ]));
    }
    if (stage.note) {
      frag.appendChild(h('div', { class: 'locked-why' }, [
        h('strong', { text: 'Outstanding \u2014 ' }), h('span', { text: stage.note })
      ]));
    }
    if (stage.gate_failed && stage.gate_failed.length) {
      frag.appendChild(h('div', { class: 'locked-why failed' },
        ['Not passing: ' + stage.gate_failed.join(', ')]));
    }
    questionGroups(stage.group_ids).forEach(function (n) { frag.appendChild(n); });

    if (stage.gates && stage.gates.length) {
      var gbox = h('div', { class: 'gates' });
      stage.gates.forEach(function (g) { gbox.appendChild(gateRow(g)); });
      frag.appendChild(h('div', { class: 'gates-wrap' }, [
        h('div', { class: 'sub muted', text: 'Pipeline stages in this step' }), gbox
      ]));
    }
    (stage.panels || []).forEach(function (p) {
      if (p === 'manual_bem') { frag.appendChild(bandManualBem()); }
      if (p === 'import') { frag.appendChild(bandImport()); }
      if (p === 'outcome') { frag.appendChild(bandOutcome()); }
      if (p === 'rerun') { frag.appendChild(bandRerun()); }
    });
    if (!stage.group_ids.length && !(stage.panels || []).length &&
        !(stage.gates || []).length) {
      frag.appendChild(h('div', { class: 'muted',
        text: 'Nothing to answer here \u2014 this step reports a pipeline result.' }));
    }
    return frag;
  }

  // Every section is built once and then shown or hidden, so any content inside
  // survives opening another stage.
  var openState = {};

  function stageAccordion(stage) {
    var headId = 'acc-h-' + stage.id;
    var bodyId = 'acc-b-' + stage.id;
    var open = (stage.id in openState) ? openState[stage.id]
                                       : !!stage.open_by_default;

    var btn = h('button', { type: 'button', class: 'acc-head', id: headId,
                            'aria-expanded': open ? 'true' : 'false',
                            'aria-controls': bodyId });
    btn.appendChild(h('span', { class: 'acc-icon', 'aria-hidden': 'true',
                               text: open ? '\u25be' : '\u25b8' }));
    btn.appendChild(h('span', { class: 'acc-name', text: stage.name }));
    btn.appendChild(h('span', { class: 'acc-count muted',
      text: stage.required_total
        ? (stage.required_answered + ' of ' + stage.required_total + ' required')
        : 'report only' }));
    if (stage.blocker_count) {
      btn.appendChild(h('span', { class: 'chip attention',
        text: stage.blocker_count + ' blocker'
              + (stage.blocker_count === 1 ? '' : 's') }));
    } else if (stage.locked) {
      btn.appendChild(h('span', { class: 'chip locked', text: 'locked' }));
    }
    btn.appendChild(h('span', { class: 'chip ' + stageChipCls(stage.status),
                               text: stageStatusWord(stage.status) }));

    var body = h('div', { class: 'acc-body', id: bodyId, role: 'region',
                          'aria-labelledby': headId });
    body.appendChild(stageBodyContent(stage));
    if (!open) { body.hidden = true; }

    btn.addEventListener('click', function () {
      var next = btn.getAttribute('aria-expanded') !== 'true';
      btn.setAttribute('aria-expanded', next ? 'true' : 'false');
      body.hidden = !next;
      btn.querySelector('.acc-icon').textContent = next ? '\u25be' : '\u25b8';
      openState[stage.id] = next;
    });

    var sec = h('section', { class: 'acc acc-' + stage.status });
    sec.appendChild(btn);
    sec.appendChild(body);
    return sec;
  }

  // standard accordion keyboard set: Up/Down between headers, Home/End to the ends
  function wireAccordionKeys(heads) {
    heads.forEach(function (btn, i) {
      btn.addEventListener('keydown', function (ev) {
        var j = null;
        if (ev.key === 'ArrowDown') { j = (i + 1) % heads.length; }
        else if (ev.key === 'ArrowUp') { j = (i - 1 + heads.length) % heads.length; }
        else if (ev.key === 'Home') { j = 0; }
        else if (ev.key === 'End') { j = heads.length - 1; }
        if (j !== null) { ev.preventDefault(); heads[j].focus(); }
      });
    });
  }


  // ---------------------------------------------------------------- W5
  function order(chain, s) { var i = (chain || []).indexOf(s); return i < 0 ? 99 : i; }

  function bandManualBem() {
    var mb = view.manual_bem || {};
    if (!mb.available) {
      var locked = band('W5 \u00b7 manual AKABAK checkpoint',
                        { text: 'locked', cls: 'locked' });
      locked.body.appendChild(h('div', { class: 'muted',
        text: 'Unlocks when FOLD_AWARE_SIMULATION has passed and the BEM inputs exist.' }));
      return locked.root;
    }
    var state = mb.state || 'INPUTS_GENERATED';
    var b = band('W5 \u00b7 manual AKABAK checkpoint',
                 { text: state, cls: bemChipClass(state) });

    var track = h('div', { class: 'gates' });
    (mb.chain || []).forEach(function (s) {
      var here = (s === state);
      var cls = here ? bemChipClass(s)
                     : (order(mb.chain, s) < order(mb.chain, state) ? 'passed' : 'optional');
      track.appendChild(h('div', { class: 'gate' }, [
        h('span', { class: 'chip ' + cls, text: here ? '\u25c9' : '\u25cb' }),
        h('span', { class: 'nm', text: s + (here ? '  \u2190 current' : '') })
      ]));
    });
    b.body.appendChild(track);
    b.body.appendChild(h('div', { class: 'muted', style: 'margin-top:6px',
      text: 'VIPS_IMPORTED is reached by the import below \u2014 not by this panel.' }));

    if (mb.reason) {
      b.body.appendChild(h('div', { class: 'na', style: 'margin-top:8px' }, [
        h('div', { class: 'why', text: mb.reason })]));
    }
    var kv = h('dl', { class: 'kv', style: 'margin-top:8px' });
    [['solver', (mb.solver_label || '\u2014')
        + (mb.solver_version ? '  (' + mb.solver_version + ')' : '')],
     ['export dir', mb.export_dir || '\u2014'],
     ['manifest', mb.manifest || '\u2014'],
     ['recipe', mb.recipe || '\u2014'],
     ['.vips found', String(mb.exported_files || 0)
        + (mb.newest_export_utc ? '  (newest ' + mb.newest_export_utc + ')' : '')]
    ].forEach(function (r) {
      kv.appendChild(h('dt', { text: r[0] }));
      kv.appendChild(h('dd', {}, [h('code', { text: String(r[1]) })]));
    });
    b.body.appendChild(kv);

    // checklist - ticks live in this browser only and never touch state
    var key = 'hornflow.ticks.' + ((view.run && view.run.run_id) || 'x');
    var ticks = {};
    try { ticks = JSON.parse(store(key) || '{}'); } catch (e) { ticks = {}; }
    var list = h('div', { style: 'margin-top:8px' });
    (mb.checklist || []).forEach(function (item) {
      var cb = h('input', { type: 'checkbox' });
      cb.checked = !!ticks[item.key];
      cb.addEventListener('change', function () {
        ticks[item.key] = cb.checked;
        store(key, JSON.stringify(ticks));
      });
      list.appendChild(h('label', { class: 'check' }, [cb, h('span', { text: item.text })]));
    });
    b.body.appendChild(list);
    b.body.appendChild(h('div', { class: 'muted',
      text: 'Ticks are a memory aid stored in this browser only; they never advance '
            + 'the run state.' }));

    b.body.appendChild(h('div', { style: 'margin-top:8px' }, [
      copyBtn('Copy AKABAK checklist',
              'Checklist file: ' + (mb.recipe || 'deliverables/bem/akabak_recipe.md')),
      ' ',
      copyBtn('Open export folder', mb.export_dir || ''),
      ' ',
      todoBtn('I exported the files',
              'A convenience flag only; the import is what advances the state (M4).')
    ]));
    b.body.appendChild(h('details', { class: 'tb', style: 'margin-top:8px' }, [
      h('summary', { text: 'Troubleshooting' }),
      h('ul', {}, [
        h('li', { text: 'no window appears \u2192 run winecfg once, then retry the launcher' }),
        h('li', { text: 'Cannot locate VACS dialog \u2192 harmless, or use the Files route' }),
        h('li', { text: 'flat or empty curve \u2192 Throat not Driven, or the diaphragm is '
                        + 'not coupled to the BEM' }),
        h('li', { text: 'model tiny or huge \u2192 the mesh is in metres; scaling must be 1' }),
        h('li', { text: 'export folder stays empty \u2192 tick Text format under VACS '
                        + '\u2192 Spectrum way of output' })
      ])
    ]));
    return b.root;
  }


  // ---------------------------------------------------------------- W6
  function bandImport() {
    var mb = view.manual_bem || {};
    var ip = view.import_panel || {};
    var chain = mb.chain || [];
    var open = mb.available && order(chain, ip.state) >= order(chain, 'MANUAL_SOLVE_PENDING');
    var b = band('W6 \u00b7 .vips import', open
      ? { text: ip.ready ? 'ready' : 'waiting', cls: ip.ready ? 'running' : 'optional' }
      : { text: 'locked', cls: 'locked' });
    if (!open) {
      b.body.appendChild(h('div', { class: 'muted',
        text: 'Unlocks at MANUAL_SOLVE_PENDING, i.e. after the GUI solve.' }));
      return b.root;
    }
    var kv = h('dl', { class: 'kv' });
    [['export dir', ip.export_dir || '\u2014'],
     ['expects', '*.vips  (required spectrum: Mic1 or H 0-90)'],
     ['enabled at', ip.enabled_when_state || 'MANUAL_SOLVE_COMPLETED'],
     ['last import', (ip.last_source || '\u2014')
        + (ip.last_utc ? '  at ' + ip.last_utc : '')],
     ['.vips found', String(mb.exported_files || 0)]
    ].forEach(function (r) {
      kv.appendChild(h('dt', { text: r[0] }));
      kv.appendChild(h('dd', {}, [h('code', { text: String(r[1]) })]));
    });
    b.body.appendChild(kv);
    b.body.appendChild(h('div', { style: 'margin-top:8px' }, [
      todoBtn('Import & validate (.vips)',
              'The import writes the validation block into state.json, so it needs the '
              + 'local host (M4). Until then copy the command below.'),
      ' ',
      copyBtn('Copy import command', ip.command || '')
    ]));
    if (ip.command) b.body.appendChild(h('pre', { class: 'cmd', text: ip.command }));
    return b.root;
  }


  // ---------------------------------------------------------------- W7
  function bandOutcome() {
    var oc = view.outcome || {};
    var chain = (view.manual_bem && view.manual_bem.chain) || [];
    var open = order(chain, oc.bem) >= order(chain, 'VIPS_IMPORTED');
    var classes = { BEM_VALIDATED: 'validated', BEM_REJECTED: 'rejected' };
    var b = band('W7 \u00b7 validation outcome', open
      ? { text: oc.bem, cls: classes[oc.bem] || 'optional' }
      : { text: 'locked', cls: 'locked' });
    if (!open) {
      b.body.appendChild(h('div', { class: 'muted',
        text: 'Unlocks at BEM_COMPARISON_COMPLETED, i.e. after a validated import.' }));
      return b.root;
    }
    var banner = h('div', { class: 'na' });
    if (oc.bem === 'BEM_VALIDATED') {
      banner.appendChild(h('div', { class: 'lbl',
        text: 'Validated against the 1-D reference' }));
    } else if (oc.bem === 'BEM_REJECTED') {
      banner.appendChild(h('div', { class: 'lbl',
        text: 'Compared, but outside tolerance' }));
      var mm0 = oc.metrics || {};
      if (mm0.mean_diff_db !== undefined) {
        banner.appendChild(h('div', { class: 'why', text:
          'mean ' + fmt(mm0.mean_diff_db, 2) + ' dB \u00b7 worst |\u0394| '
          + fmt(mm0.worst_diff_db, 2) + ' dB vs ' + fmt(oc.tolerance_db, 1)
          + ' dB tolerance' }));
      }
    } else {
      banner.appendChild(h('div', { class: 'lbl', text: 'Awaiting the import' }));
    }
    b.body.appendChild(banner);

    if ((oc.checks || []).length) {
      var t = h('table', { class: 'tbl', style: 'margin-top:8px' });
      t.appendChild(h('tr', {}, [h('th', { text: 'check' }), h('th', { text: 'result' }),
                                 h('th', { text: 'severity' }),
                                 h('th', { text: 'detail' })]));
      oc.checks.forEach(function (c) {
        t.appendChild(h('tr', {}, [
          h('td', { text: c.name }),
          h('td', { class: c.passed ? 'ok' : 'bad', text: c.passed ? 'pass' : 'FAIL' }),
          h('td', { text: c.severity || '' }),
          h('td', { text: c.detail || '' })
        ]));
      });
      b.body.appendChild(t);
    }
    var mm = oc.metrics;
    if (mm) {
      var kv = h('dl', { class: 'kv', style: 'margin-top:8px' });
      [['curve compared', mm.curve], ['points', mm.n_points],
       ['band (Hz)', mm.band_hz ? mm.band_hz[0].toFixed(0) + ' \u2013 '
                                  + mm.band_hz[1].toFixed(0) : '\u2014'],
       ['mean difference (dB)', fmt(mm.mean_diff_db, 2)],
       ['worst |difference| (dB)', fmt(mm.worst_diff_db, 2)],
       ['evidence', oc.evidence || '\u2014']
      ].forEach(function (r) {
        kv.appendChild(h('dt', { text: r[0] }));
        kv.appendChild(h('dd', { text: (r[1] === null || r[1] === undefined)
                                      ? '\u2014' : String(r[1]) }));
      });
      b.body.appendChild(kv);
      b.body.appendChild(h('div', { class: 'muted',
        text: 'The AKABAK peak-rendering convention (+3.01 dB) is removed by the .vips '
              + 'parser, so these are rms-referenced and directly comparable with the '
              + '1-D model.' }));
    }
    if (oc.critic && oc.critic.length) {
      var cr = h('div', { style: 'margin-top:8px' });
      cr.appendChild(h('div', { class: 'muted', text: 'critic' }));
      oc.critic.forEach(function (c) {
        cr.appendChild(h('div', { class: 'check' }, [
          h('span', { class: 'chip ' + (c.passed ? 'passed' : 'failed'),
                      text: c.passed ? 'pass' : (c.severity || 'reject') }),
          h('span', { text: c.check + (c.detail ? ' \u2014 ' + c.detail : '') })
        ]));
      });
      b.body.appendChild(cr);
    }
    b.body.appendChild(h('div', { style: 'margin-top:8px' }, [
      todoBtn('Re-export and retry',
              'Reopens the checklist; no state change is needed for this.'),
      ' ',
      todoBtn('Accept as unvalidated',
              'Reserved: fixed reasons plus an optional note will be required (M4), and '
              + 'it writes a decision_log entry.')
    ]));
    return b.root;
  }

  // ---------------------------------------------------------------- W8
  function bandRerun() {
    var rr = view.rerun || {};
    var b = band('W8 \u00b7 rerun',
                 { text: rr.from_stage ? 'revision needed' : 'available' });
    var kv = h('dl', { class: 'kv' });
    [['from stage', rr.from_stage || '\u2014'],
     ['reason', rr.reason || '\u2014'],
     ['keeps', (rr.keeps || []).join(', ')],
     ['regenerates', (rr.regenerates || []).join(', ')]
    ].forEach(function (r) {
      kv.appendChild(h('dt', { text: r[0] }));
      kv.appendChild(h('dd', { text: String(r[1]) }));
    });
    b.body.appendChild(kv);
    b.body.appendChild(h('div', { style: 'margin-top:8px' }, [
      todoBtn(rr.from_stage ? ('Re-run from ' + rr.from_stage) : 'Re-run from <STAGE>',
              'Reruns mint a new run id; they arrive with the local host (M4).'),
      ' ',
      todoBtn('Re-run (new revision)', 'Needs an editable brief first (M4).')
    ]));
    b.body.appendChild(h('div', { class: 'muted',
      text: 'A rerun never overwrites: HornFlow mints a new run id and the previous run '
            + 'directory stays addressable.' }));
    return b.root;
  }


  // ---------------------------------------------------------------- panes
  function renderWorkflow() {
    var pane = document.getElementById('pane-workflow');
    if (!pane) return;
    clear(pane);
    pane.appendChild(summaryBand());

    var stages = view.workflow_stages || [];
    if (!stages.length) {
      pane.appendChild(h('div', { class: 'placeholder',
        text: 'This page was generated by an older view schema and has no workflow '
              + 'stages. Re-render it with: python3 -m hornflow.cli <params> '
              + '--emit-ui <run dir>' }));
      return;
    }

    var wrap = h('div', { class: 'stages' });
    var heads = [];
    stages.forEach(function (stage) {
      var sec = stageAccordion(stage);
      wrap.appendChild(sec);
      heads.push(sec.querySelector('.acc-head'));
    });
    pane.appendChild(wrap);
    wireAccordionKeys(heads);

    var comp = view.completion || {};
    if (comp.blocker_count) {
      pane.appendChild(h('div', { class: 'muted stamp' },
        [String(comp.blocker_count) + ' required answer'
         + (comp.blocker_count === 1 ? '' : 's') + ' still missing \u2014 '
         + 'the first incomplete stage is open above.']));
    }
    if (view.host === 'static') {
      pane.appendChild(h('div', { class: 'ro-note muted',
        text: 'Read-only snapshot: HornFlow generated this page from the run '
              + 'artifacts. Actions that would change state are disabled and paired '
              + 'with a Copy command; they become live with the local host (M4).' }));
    }
  }

  function renderResults() {
    var pane = document.getElementById('pane-results');
    if (!pane) return;
    clear(pane);
    pane.appendChild(h('div', { class: 'placeholder',
      text: 'Results will render here in the next milestone: the executive decision '
            + '(best folded horn and best overall), the limit-impact table, the '
            + 'architecture comparison, sensitivity, curve plots and the artifact list.' }));
    pane.appendChild(h('div', { class: 'muted', style: 'margin-top:12px;text-align:center' }, [
      'Until then, open ', h('code', { text: 'deliverables/report.md' }), '.'
    ]));
  }

  // ---------------------------------------------------------------- dimensions
  // Decision: the overlay defaults to metres, with a visible mm toggle.
  function wireDimensions() {
    var btn = document.getElementById('btnDims');
    var unitBtn = document.getElementById('btnUnits');
    var viewDiv = document.getElementById('view');
    if (!btn || !viewDiv) return;

    var ann = view.annotations || {};
    var feats = (view.viewer && view.viewer.features) || {};
    var unit = feats.units === 'mm' ? 'mm' : 'm';
    var on = false, cache = null, labels = [], warned = false;

    var box = h('div', { id: 'dims' });
    box.style.display = 'none';
    viewDiv.appendChild(box);

    function fL(m) {
      if (m === null || m === undefined) return '\u2014';
      return unit === 'mm' ? Math.round(m * 1000) + ' mm' : m.toFixed(3) + ' m';
    }
    function fMM(mm) {
      if (mm === null || mm === undefined) return '\u2014';
      return unit === 'mm' ? Math.round(mm) + ' mm' : (mm / 1000).toFixed(3) + ' m';
    }
    function f3(v) { return fL(v.x) + ' \u00d7 ' + fL(v.y) + ' \u00d7 ' + fL(v.z); }

    function anchors() {
      if (typeof THREE === 'undefined' || typeof scene === 'undefined') return [];
      if (!scene) return [];
      var mouth = null, throat = null, n = 0;
      scene.traverse(function (o) {
        n += 1;
        if (o.name === 'mouth') mouth = o;
        if (o.name === 'throat') throat = o;
      });
      if (!n) return [];
      var bb = new THREE.Box3().setFromObject(scene);
      if (bb.isEmpty()) return [];
      var size = bb.getSize(new THREE.Vector3());
      var ctr = bb.getCenter(new THREE.Vector3());
      var out = [{ p: new THREE.Vector3(ctr.x, bb.max.y, ctr.z), label: 'bbox ' + f3(size) }];
      if (ann.path_length_m) {
        out.push({ p: new THREE.Vector3(ctr.x, bb.min.y, ctr.z),
                   label: 'path ' + fL(ann.path_length_m) });
      }
      if (mouth && ann.mouth_width_mm) {
        out.push({ p: mouth.getWorldPosition(new THREE.Vector3()),
                   label: 'mouth ' + fMM(ann.mouth_width_mm) + ' \u00d7 '
                          + fMM(ann.mouth_height_mm) });
      }
      if (throat && ann.throat_diameter_mm) {
        out.push({ p: throat.getWorldPosition(new THREE.Vector3()),
                   label: 'throat \u2300' + fMM(ann.throat_diameter_mm) });
      }
      return out;
    }

    function ensureLabels(n) {
      while (labels.length < n) {
        var d = h('div', { class: 'dim-label' });
        box.appendChild(d);
        labels.push(d);
      }
    }

    function draw() {
      if (!on) return;
      if (typeof camera === 'undefined' || !camera) return;
      if (!cache) cache = anchors();
      if (!cache.length) { cache = null; labels.forEach(function (l) { l.style.display = 'none'; }); return; }
      ensureLabels(cache.length);
      var w = viewDiv.clientWidth, hh = viewDiv.clientHeight;
      cache.forEach(function (item, i) {
        var l = labels[i];
        l.style.display = '';
        l.textContent = item.label;
        var v = item.p.clone().project(camera);
        l.style.left = ((v.x * 0.5 + 0.5) * w) + 'px';
        l.style.top = ((-v.y * 0.5 + 0.5) * hh) + 'px';
      });
      for (var k = cache.length; k < labels.length; k++) labels[k].style.display = 'none';
    }

    btn.textContent = 'Dimensions';
    btn.addEventListener('click', function () {
      on = !on;
      box.style.display = on ? '' : 'none';
      cache = null;
      btn.classList.toggle('active', on);
    });
    if (unitBtn) {
      unitBtn.textContent = unit;
      unitBtn.title = 'Dimension overlay unit (click to toggle)';
      unitBtn.addEventListener('click', function () {
        unit = (unit === 'm') ? 'mm' : 'm';
        unitBtn.textContent = unit;
        cache = null;
      });
    }
    if (!feats.dimensions) { btn.style.display = 'none'; if (unitBtn) unitBtn.style.display = 'none'; }

    (function tick() {
      window.requestAnimationFrame(tick);
      try { draw(); } catch (e) {
        if (!warned) { warned = true; log('dimension overlay disabled: ' + e.message); }
        on = false;
      }
    })();
  }

  // ------------------------------------------------------------- live wiring
  function applyView(v) {
    if (!v || !v.view_schema) { return; }
    view = v;
    var saved = store('hornflow.tab');
    renderStrip();
    renderWorkflow();
    renderResults();
    if (saved) { activate(saved); }
  }

  function poll(force) {
    if (!live.on) { return; }
    fetch('/api/progress').then(function (r) {
      return r.ok ? r.json() : null;
    }).then(function (p) {
      if (!p) { return; }
      var before = (view.live || {}).state;
      view.live = p;
      if (live.poll) { window.clearTimeout(live.poll); }
      live.poll = window.setTimeout(poll, (p.state === 'running') ? 1000 : 2500);
      // a finished run changes the whole model, so re-read it once
      if (p.state !== before && (p.state === 'done' || p.state === 'failed')) {
        fetch('/api/view').then(function (r) { return r.ok ? r.json() : null; })
          .then(function (v) { if (v) { applyView(v); } });
        return;
      }
      if (force || p.state === 'running') { refreshActions(); }
    }).catch(function () { /* the host went away; stay on the snapshot */ });
  }

  function bootLive() {
    if (!window.fetch) { return; }
    fetch('/api/view').then(function (r) {
      return r.ok ? r.json() : null;
    }).then(function (v) {
      if (!v || !v.view_schema || v.host !== 'local') { return; }
      live.on = true;
      live.dirty = {};
      note('Local host connected \u2014 the actions on this page are live.', 'ok');
      applyView(v);
      poll();
    }).catch(function () {
      log('no local host: staying on the embedded read-only snapshot');
    });
  }

  // ---------------------------------------------------------------- go
  renderStrip();
  renderWorkflow();
  renderResults();
  activate(defaultTab());
  wireDimensions();
  bootLive();
})();


