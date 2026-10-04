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
      h('span', { text: 'assumptions: ' + (cs.assumptions || 0) })
    ].forEach(function (b) { strip.appendChild(b); });
  }


  // ---------------------------------------------------------------- W1
  function bandCurrentState() {
    var cs = view.current_state || {};
    var b = band('W1 \u00b7 current state',
                 { text: view.mode, cls: bemChipClass(cs.bem_state || view.mode) });
    var kv = h('dl', { class: 'kv' });
    function row(k, v) {
      kv.appendChild(h('dt', { text: k }));
      kv.appendChild(h('dd', {}, [String(v)]));
    }
    row('run', (view.run && view.run.run_id) || 'no run yet');
    row('definition', (view.run && view.run.input_path) || '\u2014');
    row('brief revision', fmt(cs.brief_revision, 0));
    row('input hash', cs.input_hash ? String(cs.input_hash).slice(0, 24) + '\u2026' : '\u2014');
    row('stages', (cs.stages_passed || 0) + ' / ' + (cs.stages_total || 0) + ' passed');
    row('failed / blocked', (cs.stages_failed && cs.stages_failed.length)
        ? cs.stages_failed.join(', ') : 'none');
    row('BEM state', (cs.bem_state || '\u2014')
        + (cs.bem_status ? ' (' + cs.bem_status + ')' : ''));
    row('solver', cs.solver_label || '\u2014');
    row('assumptions', String(cs.assumptions || 0));
    row('validation warnings', String(cs.warnings || 0));
    b.body.appendChild(kv);
    return b.root;
  }

  // ---------------------------------------------------------------- W2
  function bandNextAction() {
    var na = view.next_action || {};
    var b = band('W2 \u00b7 next action', na.owner ? { text: 'owner: ' + na.owner } : null);
    b.body.appendChild(h('div', { class: 'na' }, [
      h('div', { class: 'lbl', text: na.label || 'nothing to do' }),
      h('div', { class: 'why', text: na.why || '' }),
      h('div', { class: 'owner', text: 'owner: ' + (na.owner || '\u2014') })
    ]));
    var cta = (na.cta || {});
    if (cta.kind === 'copy_command' && cta.value) {
      b.body.appendChild(h('div', {}, [copyBtn('Copy command', cta.value)]));
      b.body.appendChild(h('pre', { class: 'cmd', text: cta.value }));
    } else if (cta.kind === 'open_url' && cta.value) {
      b.body.appendChild(h('div', {}, [h('a', { class: 'btn', href: cta.value,
                                                target: '_blank' }, ['Open'])]));
    } else {
      b.body.appendChild(h('div', {}, [todoBtn(
        na.label || 'action',
        'This action mutates state; it arrives with the local host (M4).')]));
    }
    if (na.blockers && na.blockers.length) {
      b.body.appendChild(h('div', { class: 'muted',
                                    text: 'blocked by: ' + na.blockers.join(', ') }));
    }
    // reserved area (decision: run progress will be polled from logs.jsonl)
    b.body.appendChild(h('div', { class: 'placeholder', style: 'margin-top:10px',
      text: 'Run progress \u2014 reserved. M4 will stream logs.jsonl here while a run '
            + 'is in flight.' }));
    return b.root;
  }


  // ---------------------------------------------------------------- W3
  function bandGates() {
    var gates = view.gates || [];
    var failed = gates.filter(function (g) {
      return g.status === 'failed' || g.status === 'blocked';
    }).length;
    var b = band('W3 \u00b7 gates', failed
      ? { text: failed + ' not passing', cls: 'failed' }
      : { text: gates.length + ' stages', cls: 'passed' });
    var grid = h('div', { class: 'gates' });
    gates.forEach(function (g) {
      var mark = g.status === 'passed' ? '\u2713'
        : g.status === 'skipped' ? '\u2013'
        : (g.status === 'failed' || g.status === 'blocked') ? '\u2717'
        : g.status === 'running' ? '\u22ef' : '\u25cb';
      var cls = g.status === 'passed' ? 'passed'
        : (g.status === 'failed' || g.status === 'blocked') ? 'failed'
        : g.status === 'skipped' ? 'optional' : '';
      var kids = [h('span', { class: 'chip ' + cls, text: mark }),
                  h('span', { class: 'nm',
                              text: g.stage + (g.optional ? ' (optional)' : '') })];
      if (g.duration_s !== null && g.duration_s !== undefined) {
        kids.push(h('span', { class: 'dur', text: Number(g.duration_s).toFixed(2) + ' s' }));
      }
      var item = h('div', { class: 'gate' }, kids);
      var tip = [g.detail, (g.blocked_by && g.blocked_by.length)
        ? 'blocked by: ' + g.blocked_by.join(', ') : ''].filter(Boolean).join(' | ');
      if (tip) item.title = tip;
      grid.appendChild(item);
    });
    b.body.appendChild(grid);
    return b.root;
  }

  // ---------------------------------------------------------------- W4
  function bandQuestions() {
    var qs = view.questions || [];
    var missing = qs.filter(function (q) { return q.blocking; }).length;
    var b = band('W4 \u00b7 required questions', missing
      ? { text: missing + ' blocking', cls: 'failed' }
      : { text: 'wave A complete', cls: 'passed' });
    qs.forEach(function (q) {
      var box = h('div', { class: 'q' });
      box.appendChild(h('div', {}, [
        h('span', { class: 'pr', text: q.prompt }),
        h('span', { class: 'chip ' + (q.blocking ? 'failed' : 'passed') + ' kick',
                    text: q.fields_answered + '/' + q.fields_total })
      ]));
      box.appendChild(h('div', { class: 'why', text: q.why || '' }));
      var fields = h('div', { class: 'fields' });
      (q.fields || []).forEach(function (f) {
        var unanswered = (f.value === null || f.value === undefined);
        fields.appendChild(h('div', { class: 'field' }, [
          h('span', { class: 'fn', text: f.name + (f.unit ? ' [' + f.unit + ']' : '') }),
          h('span', { class: 'fv' + (unanswered ? ' unknown' : ''),
                      text: unanswered ? 'unanswered'
                                       : fmt(f.value, 3) + (f.unit ? ' ' + f.unit : '') }),
          h('span', { class: 'chip', text: f.status || 'UNKNOWN' })
        ]));
      });
      box.appendChild(fields);
      b.body.appendChild(box);
    });
    b.body.appendChild(h('div', {}, [
      todoBtn('Save draft', 'Editing the brief arrives with the local host (M4).'),
      ' ',
      todoBtn('Freeze brief', 'Freezing writes the brief and its input hash (M4).')
    ]));
    b.body.appendChild(h('div', { class: 'muted', style: 'margin-top:6px',
      text: 'The brief is written as a YAML definition file the existing config loader '
            + 'already understands; until M4 these fields are read-only.' }));
    return b.root;
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
    if (view.mode === 'first_run') {
      pane.appendChild(h('div', { class: 'placeholder', style: 'margin-bottom:12px',
        text: 'No run yet. Answer the five required questions below, freeze the brief, '
              + 'then start a run.' }));
    }
    [bandCurrentState(), bandNextAction(), bandGates(), bandQuestions(),
     bandManualBem(), bandImport(), bandOutcome(), bandRerun()].forEach(function (n) {
      if (n) pane.appendChild(n);
    });
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

  // ---------------------------------------------------------------- go
  renderStrip();
  renderWorkflow();
  renderResults();
  activate(defaultTab());
  wireDimensions();
})();

