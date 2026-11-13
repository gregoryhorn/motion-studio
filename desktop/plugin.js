// studio/native/frontend/entry.js
import { createElement, useState as useState10 } from "react";
import { host, ROUTES_AREA, SIDEBAR_NAV_AREA } from "@hermes/plugin-sdk";

// studio/native/frontend/transport.js
var technicalMethods = /* @__PURE__ */ new Set(["evidence.select", "evidence.read", "prepare", "status", "result", "abandon"]);
var provenRejections = /* @__PURE__ */ new Set([
  "SYNTHESIS_PACKET_TOO_LARGE",
  "SYNTHESIS_UNAVAILABLE",
  "SYNTHESIS_STALE",
  "TECHNICAL_PREPARATION_ACTIVE",
  "TECHNICAL_ACCESS_UNAVAILABLE",
  "TECHNICAL_STORE_BUSY",
  "TECHNICAL_STORE_REVIEW_REQUIRED"
]);
var technicalUnavailable = () => new Error("TECHNICAL_PRIMARY_UNAVAILABLE");
async function openTechnical(host2, onInvalidated = () => {
}, options = {}) {
  const methods3 = options.methods || technicalMethods, namespace = options.namespace || "technical";
  const workspace = ["creation", "production", "director"].includes(namespace);
  const unavailable = () => workspace ? Object.assign(
    new Error("WORKSPACE_PRIMARY_UNAVAILABLE"),
    { code: namespace.toUpperCase() + "_PRIMARY_UNAVAILABLE" }
  ) : technicalUnavailable();
  const keys = ["focusedSessionId", "focusedSessionOwner", "connectionId", "profile", "gateway"];
  if (!host2?.request || !host2?.profileRoutes || keys.some((key) => !host2.state?.[key]?.subscribe)) throw unavailable();
  const project = (key, value) => key === "focusedSessionOwner" && value ? { connectionId: value.connectionId, profile: value.profile } : value;
  const capture = () => Object.fromEntries(keys.map((key) => [key, project(key, host2.state[key].get())]));
  let invalid = false, disposed = false;
  const subscriptions = [];
  const dispose = () => {
    disposed = true;
    subscriptions.splice(0).forEach((stop) => stop());
  };
  try {
    for (const key of keys) {
      let notified = false, previous;
      subscriptions.push(host2.state[key].subscribe((value) => {
        const next = JSON.stringify(project(key, value));
        if (notified && next !== previous && !invalid) {
          invalid = true;
          onInvalidated();
        }
        notified = true;
        previous = next;
      }));
    }
    const initial = capture(), owner = initial.focusedSessionOwner;
    const current = () => !disposed && !invalid && JSON.stringify(capture()) === JSON.stringify(initial);
    if (!initial.focusedSessionId || !owner || initial.gateway !== "open" || owner.connectionId !== initial.connectionId || owner.profile !== initial.profile) throw unavailable();
    const routes = await host2.profileRoutes();
    if (!current() || routes.filter((r) => r.primary === true && (r.mode === "local" || workspace && r.mode === "remote") && r.connectionId === owner.connectionId && r.profile === owner.profile && r.targetProfile === initial.profile).length !== 1) throw unavailable();
    return Object.freeze({
      current,
      dispose,
      session: initial.focusedSessionId,
      scope: JSON.stringify([initial.connectionId, initial.profile, initial.focusedSessionId]),
      async request(operation, payload = {}) {
        if (!methods3.has(operation) || !current()) throw unavailable();
        const response = await host2.request("plugin.motion-studio." + namespace + "." + operation, { ...payload, session_id: initial.focusedSessionId }, 15e3);
        if (!current()) throw unavailable();
        if (response?.error) {
          const error = new Error("TECHNICAL_REQUEST_REFUSED");
          error.code = typeof response.error === "string" ? response.error : "TECHNICAL_OPERATION_UNAVAILABLE";
          error.preAdmissionRejected = operation === "prepare" && response.pre_admission === true && provenRejections.has(error.code);
          throw error;
        }
        return response;
      }
    });
  } catch (error) {
    dispose();
    throw error;
  }
}

// studio/native/frontend/controller.js
var technicalEmpty = () => Array.from({ length: 3 }, () => ({ source: "", version: "", text: "" }));
var technicalMessages = {
  TECHNICAL_ACCESS_UNAVAILABLE: "Public technical access is unconfigured. Audience and plugin-store ownership require admission.",
  TECHNICAL_PRIMARY_UNAVAILABLE: "Select the supported already-open local primary session, then explicitly reopen.",
  TECHNICAL_EVIDENCE_EXCLUDED: "Evidence excluded by the technical/privacy gate. Correct selected public excerpts.",
  SYNTHESIS_PACKET_TOO_LARGE: "Technical packet too large. Shorten excerpts and deliberately prepare again.",
  SYNTHESIS_UNAVAILABLE: "Inference is unconfigured or its effective destination/fallback/data/cost policy is unverified.",
  TECHNICAL_PREPARATION_ACTIVE: "Another technical preparation is active. No queue or automatic retry.",
  TECHNICAL_EVIDENCE_STALE: "The selected evidence changed. Reopen its current revision before selecting again.",
  SYNTHESIS_STALE: "The selected evidence or template changed before preparation was admitted. Reopen the current evidence, review it and deliberately prepare again.",
  TECHNICAL_STORE_BUSY: "Another service owns the technical proposal store. Wait and explicitly reopen saved work.",
  TECHNICAL_STORE_REVIEW_REQUIRED: "Plugin store identity/ownership needs review. No automatic adoption.",
  TECHNICAL_RECOVERY_UNAVAILABLE: "Cannot retain the scoped recovery command. No preparation was dispatched."
};
var TechnicalController = class {
  constructor(host2, storage, notify = () => {
  }) {
    this.host = host2;
    this.storage = storage;
    this.notify = notify;
    this.client = null;
    this.generation = 0;
    this.disposed = false;
    this.state = {
      forms: technicalEmpty(),
      pending: false,
      connected: false,
      inference: false,
      selected: null,
      job: null,
      command: null,
      dirty: false,
      status: "Public technical lane not opened. Inference unconfigured/unverified; private media and native generation unavailable."
    };
  }
  emit(value) {
    Object.assign(this.state, value);
    if (!this.disposed) this.notify({ ...this.state });
  }
  key() {
    return "technical-command:" + this.client.scope;
  }
  pointer(command3) {
    if (command3) {
      this.storage.set(this.key(), { command: command3 });
      if (this.storage.get(this.key(), null)?.command !== command3) throw Object.assign(new Error("TECHNICAL_RECOVERY_UNAVAILABLE"), { code: "TECHNICAL_RECOVERY_UNAVAILABLE" });
    } else if (this.storage.get(this.key(), null)?.command === this.state.command) this.storage.remove(this.key());
  }
  invalidate() {
    this.generation++;
    this.emit({
      connected: false,
      pending: false,
      forms: technicalEmpty(),
      selected: null,
      job: null,
      status: "Session/connection changed. This view is invalid. Explicitly reopen to reconcile saved work; no resubmission."
    });
  }
  edit(index, key, value) {
    if (this.state.pending || this.state.command && !this.state.job?.id) return;
    const forms = this.state.forms.map((item, i) => i === index ? { ...item, [key]: value } : item);
    this.emit({ forms, dirty: true });
  }
  async transaction(task) {
    if (this.disposed || this.state.pending) return;
    const generation = ++this.generation, owned = () => !this.disposed && generation === this.generation;
    this.emit({ pending: true });
    try {
      await task(owned);
    } catch (error) {
      if (owned()) {
        if (error?.code === "SYNTHESIS_UNAVAILABLE") this.emit({ inference: false });
        if (error?.code === "TECHNICAL_ACCESS_UNAVAILABLE") this.emit({ connected: false });
        this.emit({ status: (technicalMessages[error?.code] || technicalMessages[error?.message] || "Technical operation unavailable or response unobserved. Reopen/check the same command; no automatic retry.") + (error?.prepareNotAdmitted === true ? " This Prepare was not admitted." : "") });
      }
    } finally {
      if (owned()) this.emit({ pending: false });
    }
  }
  usable(owned) {
    return owned() && this.client?.current();
  }
  open() {
    return this.transaction(async (owned) => {
      this.client?.dispose();
      this.emit({ connected: false, selected: null, job: null, command: null, forms: technicalEmpty() });
      const client = await openTechnical(this.host, () => this.invalidate());
      if (!owned()) {
        client.dispose();
        return;
      }
      this.client = client;
      const status = await client.request("status");
      if (!this.usable(owned)) return;
      this.emit({ connected: true, inference: status.inference === "admitted", status: "Public technical records opened. " + status.audience });
      const pointer = this.storage.get(this.key(), null);
      if (status.current) {
        const selected = await client.request("evidence.read", { evidence: status.current.id });
        if (!this.usable(owned)) return;
        this.emit({ selected, dirty: false, forms: [...selected.body.sources.map((s) => ({ source: s.source, version: s.version, text: s.excerpts.map((e) => e.text).join("\n") })), ...technicalEmpty()].slice(0, 3) });
      }
      let job;
      if (pointer?.command) {
        this.emit({ command: pointer.command });
        job = await client.request("status", { command: pointer.command });
        if (!this.usable(owned)) return;
      } else job = status.latest?.[0];
      if (job?.id) {
        job = await client.request("result", { job: job.id });
        if (!this.usable(owned)) return;
        this.show(job);
      } else if (pointer?.command) this.emit({ job: null, status: "Command not yet observed. Delivery is uncertain; check the same command, never infer cancellation or resubmit." });
    });
  }
  show(job) {
    if (!job.id) {
      this.emit({ job: null, status: "Command not yet observed. Outcome uncertain; check again without resubmitting." });
      return;
    }
    if (!job.active && this.state.command) {
      this.pointer(null);
      this.emit({ command: null });
    }
    this.emit({ job, status: job.state + ". Disabled/unqualified proposal only. Abandon after dispatch discards outcome, not provider cancellation or zero cost." });
  }
  select() {
    if (!this.state.connected || this.state.command && !this.state.job?.id || this.state.job?.active) return;
    const sources = this.state.forms.filter((s) => s.source || s.version || s.text).map((s, i) => ({
      id: "source-" + i,
      source: s.source,
      version: s.version,
      kind: "selected-technical-excerpt",
      excerpts: s.text.split(/\n+/).filter((t) => t.trim()).map((text, j) => ({ id: "part-" + j, section: "Selected technical reference", text: text.trim() }))
    }));
    const expected = this.state.selected?.revision || 0;
    return this.transaction(async (owned) => {
      if (!this.usable(owned)) return;
      const selected = await this.client.request("evidence.select", { expected, selection: { sources } });
      if (!this.usable(owned)) return;
      this.emit({ selected, dirty: false, status: "Technical evidence revision saved. No inference or tool operation occurred." });
    });
  }
  prepare() {
    if (!this.state.connected || !this.state.inference || this.state.dirty || !this.state.selected || this.state.command && !this.state.job?.id || this.state.job?.active) return;
    const selected = this.state.selected;
    return this.transaction(async (owned) => {
      if (!this.usable(owned)) return;
      const previous = this.storage.get(this.key(), null)?.command;
      if (previous) {
        this.emit({ command: previous, status: "A scoped command already needs reconciliation. Check saved work; no new preparation dispatched." });
        return;
      }
      const command3 = crypto.randomUUID().replaceAll("-", "");
      this.pointer(command3);
      this.emit({ command: command3, job: null });
      if (!this.usable(owned)) return;
      let job;
      try {
        job = await this.client.request("prepare", { command: command3, evidence: selected.id, revision: selected.revision, template: selected.template });
      } catch (error) {
        if (this.usable(owned) && error?.preAdmissionRejected === true && [
          "SYNTHESIS_PACKET_TOO_LARGE",
          "SYNTHESIS_UNAVAILABLE",
          "SYNTHESIS_STALE",
          "TECHNICAL_PREPARATION_ACTIVE",
          "TECHNICAL_ACCESS_UNAVAILABLE",
          "TECHNICAL_STORE_BUSY",
          "TECHNICAL_STORE_REVIEW_REQUIRED"
        ].includes(error.code)) {
          error.prepareNotAdmitted = true;
          if (this.state.command === command3 && this.storage.get(this.key(), null)?.command === command3) {
            this.pointer(null);
            this.emit({ command: null, job: null });
          }
        }
        throw error;
      }
      if (this.usable(owned)) this.show(job);
    });
  }
  check() {
    return this.open();
  }
  // Explicit observation/recovery, never Prepare.
  abandon() {
    if (!this.state.connected || !this.state.job?.id || !this.state.job.active) return;
    const id = this.state.job.id;
    return this.transaction(async (owned) => {
      if (!this.usable(owned)) return;
      const job = await this.client.request("abandon", { job: id });
      if (this.usable(owned)) this.show(job);
    });
  }
  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.generation++;
    this.client?.dispose();
    this.state = { forms: technicalEmpty(), pending: false, connected: false };
  }
};

// studio/native/frontend/page.js
import { createElement as h, useEffect, useRef, useState } from "react";
import { Button, Input, Textarea } from "@hermes/plugin-sdk";
function TechnicalPage({ createController }) {
  const controller = useRef(null), [state, setState] = useState(null);
  useEffect(() => {
    const current = createController(setState);
    controller.current = current;
    setState({ ...current.state });
    return () => {
      current.dispose();
      controller.current = null;
    };
  }, [createController]);
  if (!state) return h("p", null, "Motion Studio public technical lane. No work started.");
  const busy = state.pending, uncertain = Boolean(state.command && !state.job?.id), active = state.job?.active;
  const button = (label, action, disabled = false) => h(Button, { onClick: () => controller.current?.[action](), disabled: busy || disabled }, label);
  const fields = state.forms.map((form, index) => h(
    "fieldset",
    { key: index, disabled: busy || uncertain || active },
    h("legend", null, "Selected public technical source " + (index + 1) + (index ? " (optional)" : "")),
    ...[["source", "Public provenance"], ["version", "Documented version"], ["text", "Technical excerpts"]].map(([key, label]) => h("label", { key }, label, h(key === "text" ? Textarea : Input, {
      "aria-label": label + " " + (index + 1),
      value: form[key],
      maxLength: key === "text" ? 24576 : 200,
      onChange: (event) => controller.current?.edit(index, key, event.target.value)
    })))
  ));
  return h(
    "section",
    { "aria-label": "Motion Studio" },
    h("h1", null, "Motion Studio"),
    h("h2", null, "Quick Create / Production"),
    h("p", null, "This is the separate public technical lane, not media generation. Back to creations opens the source-only native SFX workspace; live media/generation remains unqualified. Music, Voice, Image, Video and Production remain incomplete."),
    h("h2", null, "Prepare technical proposal"),
    h("p", null, "Public/non-personal technical excerpts only. No private creative prompts, chat, files, configuration, credentials or media. Provenance is not fetched. Finite technical-sentence recognition is not arbitrary-document intelligence; a privacy filter cannot prove prose safe."),
    h("p", null, "Audience: clients authorized by the gateway to control this session, including operators and multiple controlling clients. This is not exclusive-owner, LOCAL-only or private-workspace proof. Host session restoration/bookkeeping may occur."),
    h("p", null, "Inference is unavailable until effective primary/fallback destinations, retries, data/cost policy and audience/store ownership are admitted. One app invocation is not one provider attempt or a hard spending cap."),
    h("p", { role: "status" }, state.status),
    button("Open / reconcile saved technical work", "open"),
    h("p", null, state.connected ? "Public record access observed. Inference " + (state.inference ? "admitted for this status observation." : "unconfigured/unverified.") : "No admitted public record access observed. Nothing is inferred."),
    ...fields,
    button("Save selected technical evidence", "select", !state.connected || uncertain || active),
    button("Prepare disabled proposal", "prepare", !state.connected || !state.inference || state.dirty || !state.selected || uncertain || active),
    button("Check saved work", "check"),
    button("Abandon proposal", "abandon", !state.connected || !state.job?.id || !active),
    state.job ? h("p", null, "Saved job " + state.job.id + (state.selected && state.job.evidence !== state.selected.id ? " is historical, not preparation of the current evidence." : "")) : null,
    ...(state.job?.result?.questions || []).map((question, index) => h("p", { key: index }, question + " Add the documented fact to a new evidence revision; no schema/command authoring.")),
    h(
      "details",
      null,
      h("summary", null, "Disabled proposal and evidence details"),
      h("pre", null, state.job?.result ? JSON.stringify(state.job.result, null, 2) : "No validated result observed.")
    )
  );
}

// studio/native/frontend/creation-page.js
import { createElement as h6, useEffect as useEffect4, useRef as useRef4, useState as useState3 } from "react";
import { Button as Button2, Textarea as Textarea3 } from "@hermes/plugin-sdk";

// studio/native/frontend/help.js
import { createElement as h2, useEffect as useEffect2, useRef as useRef2 } from "react";
var CREATE_HELP = {
  quick: [
    ["Describe it", "Type what you want and pick a media type. Plain language is fine."],
    ["Send from chat", "Create in chat puts your request in the Hermes chat. You press Send."],
    ["Review and compare", "New takes appear in Recent creations. Play, view and compare each one."],
    ["Keep the best", "Choose a take, mark whether it is right, or ask for a variation."]
  ],
  guide: [
    { title: "What Quick Create is for", body: ["Request one sound, track, voice line, image or clip without setting up a project. Sent requests and retained takes are saved. Unsent text is kept only in this window and cleared when chat/profile/connection authority changes."] },
    { title: "Making something", body: [
      'Describe the result in the box, for example "an 8-second loop of rain on a tin roof, no voices or music". Pick the media type, then choose Create in chat.',
      "The request is placed in your selected Hermes chat as a draft. Nothing starts until you press Send in the chat. Hermes uses sensible defaults and only asks a question if something important is missing.",
      "If the chat already has text, use Add to existing draft so nothing you typed is lost."
    ] },
    { title: "Reviewing takes", body: [
      "Select a creation on the left to see its takes. Play (or Show image) fetches the exact saved file and shows it in the take card; nothing plays until you ask.",
      "Choose marks the take you want to keep. Sounds right / Looks right and Needs work record your judgement; they do not change the file.",
      "Open Production opens the workspace only. To bring this take into a project, pick it under References there.",
      "Save / download retrieves the retained file. Derivatives are labeled separately from originals; source bytes remain separately retained. A click does not verify destination delivery."
    ] },
    { title: "Asking for a variation", body: ['Write the change under Ask for a variation, e.g. "shorter, with a softer ending". It is drafted into the chat as a new take of the same creation, so earlier takes are kept.'] },
    { title: "Status badges", body: ["Technical validation, listening/viewing review, intended-use eligibility and user approval are separate checks. Outstanding checks are shown on each take; a saved run state does not prove full quality approval. Selected means the take you chose, not commercial clearance."] },
    { title: "What each media type can do today", body: [
      "Sound effects has the recorded local Stable Audio qualification. Consult the method picker for passive tool/model/key observations, restrictions and cost uncertainty; presence is not execution admission.",
      "Image, Voice and Video have collection support. That alone does not qualify generation, recovery or intended-use eligibility on your installed route.",
      "Music: the local music engine is not enabled yet; you can import a track and review, compare and export it like any other take."
    ] },
    { title: "If something goes wrong", body: [
      "Each action shows a busy label, then a green result or amber problem beside its button for about six seconds. The top right also shows the result. After Create in chat, follow the arrow to your chat and press Send there. Opening and refreshing show the number of saved creations; changed cards briefly highlight.",
      "If it says to open a chat, select your Motion Studio chat in Hermes and choose Open saved creations. Connections lets an administrator connect this chat to the Motion Studio workflow."
    ] }
  ]
};
var PRODUCTION_HELP = {
  quick: [
    ["Write a brief", "Give the project a title and say what it is for."],
    ["Plan the assets", "Add the sounds, images, voice, music and video the project needs."],
    ["Create or import takes", "Ask Hermes for a take, or import one you made elsewhere."],
    ["Review and export", "Compare takes, use the best one for each asset, then export."]
  ],
  guide: [
    { title: "What Production is for", body: ["Keep several related assets together: a brief, references, an asset plan, the takes for each asset and the files you finally choose."] },
    { title: "Brief", body: ["Title and a short description are enough. Purpose, audience and usage are optional context. Saving a brief never starts generation."] },
    { title: "Plan", body: [
      'Each asset is one thing you need, such as "door slam" or "opening title image". Set its media type, what it should be, its order and what it depends on.',
      "If you change something an asset depends on, its chosen take is marked out of date instead of being replaced."
    ] },
    { title: "References", body: ["Link earlier creations as references for an asset so the next takes stay consistent. References always point to the original saved file."] },
    { title: "Takes", body: [
      "Create with Hermes drafts a request for the selected asset into your chat; you press Send. Import a take adds a file you made elsewhere (PNG, JPEG, WAV or MP4). Originals are never changed.",
      "Compare plays two takes from the same starting point at the same volume. Use take makes it the chosen take for that asset only."
    ] },
    { title: "Outputs and export", body: ["Outputs lists the chosen take for every asset. Export assets packages exactly those files into one ZIP with a short manifest, ready for your editor."] },
    { title: "If something goes wrong", body: [
      "The message at the top right says what happened. Opening a project, editing the plan and reviewing never generate anything.",
      "Out of date means an input changed after the take was chosen; review it and choose again when ready."
    ] }
  ]
};
function QuickHelp({ steps, label = "How it works" }) {
  return h2("ol", { className: "ms-steps", "aria-label": label }, ...steps.map(([title, text], index) => h2(
    "li",
    { key: title, className: "ms-step" },
    h2("span", { className: "ms-step-n", "aria-hidden": true }, index + 1),
    h2("span", null, h2("strong", null, title), h2("span", { className: "ms-step-text" }, text))
  )));
}
function HelpPanel({ open, onClose, title, guide }) {
  const heading = useRef2(null);
  useEffect2(() => {
    if (!open) return;
    const invoker = document.activeElement;
    heading.current?.focus();
    return () => {
      if (invoker?.isConnected) invoker.focus();
    };
  }, [open]);
  if (!open) return null;
  const close = () => onClose();
  return h2(
    "section",
    {
      className: "ms-help-panel",
      role: "region",
      "aria-label": title + " help",
      onKeyDown: (event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          close();
        }
      }
    },
    h2(
      "div",
      { className: "ms-help-head" },
      h2("h2", { ref: heading, tabIndex: -1 }, title + " guide"),
      h2("button", { type: "button", className: "ms-tab", onClick: close }, "Close help")
    ),
    h2("div", { className: "ms-help-grid" }, ...guide.map((section) => h2(
      "article",
      { key: section.title, className: "ms-help-section" },
      h2("h3", null, section.title),
      ...section.body.map((text, index) => h2("p", { key: index }, text))
    )))
  );
}
var helpStyles = `
.ms-steps{list-style:none;margin:0 0 24px;padding:0;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.ms-step{display:flex;gap:10px;align-items:flex-start;border:1px solid var(--ms-line);border-radius:12px;padding:12px;background:var(--ms-surface)}
.ms-step strong{display:block;font-size:13px}.ms-step-text{display:block;color:var(--ms-muted);font-size:12.5px;line-height:1.4;margin-top:2px}
.ms-step-n{flex:none;width:24px;height:24px;border-radius:50%;display:grid;place-items:center;font-size:12px;font-weight:700;background:var(--ms-raised);color:var(--ms-text)}
.ms-help-panel{border:1px solid color-mix(in srgb,var(--ms-accent) 45%,var(--ms-line));border-radius:16px;background:var(--ms-surface);padding:20px 22px;margin:0 0 24px}
.ms-help-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}
.ms-help-head h2{font-size:1.2rem}.ms-help-head h2:focus{outline:none}
.ms-help-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px 24px}
.ms-help-section h3{font-size:.95rem;margin-bottom:6px}.ms-help-section p{color:var(--ms-muted);margin:0 0 8px!important;line-height:1.5}
@media(max-width:820px){.ms-steps{grid-template-columns:1fr 1fr}}@media(max-width:480px){.ms-steps{grid-template-columns:1fr}}
`;

// studio/native/frontend/methods-ui.js
import { createElement as h3 } from "react";
var COST = { free: ["Free", "good"], subscription: ["Included in subscription", "good"], paid: ["Paid per use", "warn"], unknown: ["Cost unknown", "warn"] };
function costLabel(cost) {
  return (COST[cost] || COST.unknown)[0];
}
function chosenMethod(methods3, kind, choice) {
  const entry = methods3?.kinds?.[kind], options = entry?.options || [];
  if (choice) return options.find((item) => item.id === choice) || { id: choice, label: "Previously selected method", available: false, reason: "This method is no longer listed. Choose an alternative deliberately." };
  const creates = (item) => item.available && item.id !== "import" && item.engine !== "import";
  return options.find((item) => item.id === entry?.default && creates(item)) || options.find(creates) || null;
}
function MethodPicker({ methods: methods3, kind, choice, onChoose, idPrefix = "ms-method", loadingError = false }) {
  const entry = methods3?.kinds?.[kind];
  if (!entry) return h3("p", { className: "ms-help ms-method-empty" }, loadingError ? "Method information could not be loaded. Retry loading deliberately." : methods3 ? "No method information for " + kind + "." : "Checking which methods are available on this PC...");
  const current = chosenMethod(methods3, kind, choice), listed = entry.options || [];
  const options = current && !listed.some((item) => item.id === current.id) ? [current, ...listed] : listed;
  const importing = current?.action === "import" || current?.engine === "import" || current?.id === "import";
  const [label, tone2] = current?.available ? importing ? ["Import existing file", void 0] : COST[current.cost] || COST.unknown : ["Unavailable - choose another method", "warn"];
  return h3(
    "div",
    { className: "ms-method" },
    h3("label", { className: "ms-method-label", htmlFor: idPrefix }, "Method"),
    h3(
      "select",
      { id: idPrefix, className: "ms-method-select", value: current?.id || choice || "", onChange: (event) => onChoose(event.target.value) },
      ...current || choice ? [] : [h3("option", { key: "", value: "", disabled: true }, "Choose a method")],
      ...options.map((item) => h3(
        "option",
        { key: item.id, value: item.id, disabled: !item.available },
        item.label + (item.id === entry.default ? " (default)" : "") + " - " + (item.available ? costLabel(item.cost) : item.reason || "Not available")
      ))
    ),
    h3("span", { className: "ms-badge", "data-tone": tone2 }, label),
    current ? h3("span", { className: "ms-badge" }, importing ? "Existing file" : current.engine === "local" ? "Runs on this PC" : "Cloud") : null,
    current && !current.available ? h3("span", { className: "ms-help ms-method-note" }, current.reason || "Not available; choose an alternative deliberately.") : null,
    current?.note ? h3("span", { className: "ms-help ms-method-note" }, current.note) : null,
    current && !importing ? h3("span", { className: "ms-help ms-method-note" }, "Operation qualification: " + (current.operation_qualified || "unknown") + ". Intended-use permission: " + (current.permitted_for_use || "not assessed") + ". Presence is not admission.") : null,
    h3(
      "details",
      { className: "ms-method-all" },
      h3("summary", null, "All " + kind + " options (" + options.filter((item) => item.available).length + " of " + options.length + " set up)"),
      h3("p", { className: "ms-help" }, "Set up means the tool, model or key was found on this PC. It has not been test-run for this request."),
      h3("ul", null, ...options.map((item) => h3(
        "li",
        { key: item.id },
        h3("strong", null, item.label),
        " - ",
        item.engine === "local" ? "local" : "cloud",
        ", ",
        item.available ? costLabel(item.cost) : "unavailable: " + (item.reason || "not set up"),
        item.note ? " - " + item.note : ""
      )))
    )
  );
}
var methodStyles = `
.ms-method{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:10px 12px;border-top:1px solid var(--ms-line)}
.ms-method-label{font-weight:650;font-size:12.5px;color:var(--ms-muted)}
.ms-method-select{background:var(--ms-bg);color:var(--ms-text);border:1px solid var(--ms-line);border-radius:8px;min-height:32px;padding:0 8px;font:inherit;max-width:100%}
.ms-method-note{margin:0!important}
.ms-method-all{flex-basis:100%;font-size:12.5px;color:var(--ms-muted)}.ms-method-all summary{cursor:pointer}
.ms-method-all ul{margin:6px 0 0;padding-left:18px;columns:2 260px}.ms-method-all li{margin:2px 0;break-inside:avoid}
.ms-method-empty{padding:10px 12px;margin:0!important;border-top:1px solid var(--ms-line)}
`;

// studio/native/frontend/creation-style.js
var themeStyles = helpStyles + methodStyles + `
.ms{--ms-bg:color-mix(in srgb,var(--ms-text) 2%,transparent);--ms-surface:color-mix(in srgb,var(--ms-text) 4%,transparent);--ms-raised:color-mix(in srgb,var(--ms-text) 8%,transparent);
--ms-text:var(--ui-text-primary,#f2ecdf);--ms-muted:var(--ui-text-secondary,#a7afab);--ms-faint:var(--ui-text-tertiary,#7d8581);
--ms-line:color-mix(in srgb,var(--ms-text) 14%,transparent);--ms-accent:var(--ui-accent-primary,var(--ui-accent,#8fe3c0));--ms-warn:var(--ui-warning-primary,#e8b45a);
box-sizing:border-box;color:var(--ms-text);background:transparent;min-height:100%;padding:28px 32px 40px!important;max-width:none!important;margin:0!important;font-size:14px;line-height:1.5}
.ms *{box-sizing:border-box}
.ms-inner{max-width:1440px;margin:0 auto}
.ms h1,.ms h2,.ms h3{margin:0;font-weight:650;letter-spacing:-.01em}
.ms p{margin:0;overflow-wrap:anywhere}
.ms-top{display:flex;align-items:center;gap:20px;flex-wrap:wrap;min-height:56px;padding:0 0 18px;margin:0 0 28px;border-bottom:1px solid var(--ms-line)}
.ms.ms .ms-top .ms-tab{min-height:0;height:36px;padding:0 14px;margin:0;border:0;line-height:36px;font-size:14px}
.ms.ms .ms-top h1,.ms.ms .ms-top .ms-brand{margin:0;font-size:1.25rem;line-height:36px}
.ms-brand{display:flex;align-items:center;gap:10px;font-size:1.25rem;font-weight:700}
.ms-mark{width:26px;height:18px;border-radius:4px;background:linear-gradient(90deg,var(--ms-accent) 0 30%,transparent 30% 35%,var(--ms-accent) 35% 65%,transparent 65% 70%,var(--ms-accent) 70%);transform:skewX(-14deg)}
.ms-tabs{display:flex;gap:4px;flex-wrap:wrap}
.ms-tab{appearance:none;border:0;background:transparent;color:var(--ms-muted);font:inherit;font-weight:600;padding:8px 14px;border-radius:8px;cursor:pointer}
.ms-tab:hover{color:var(--ms-text);background:var(--ms-raised)}
.ms-tab[aria-current="page"]{color:var(--ms-text);background:color-mix(in srgb,var(--ms-accent) 18%,transparent);box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--ms-accent) 45%,transparent)}
.ms-spacer{flex:1}
.ms-status{font-size:12.5px;color:var(--ms-muted);display:flex;align-items:center;gap:8px;min-height:20px}
.ms-status::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--ms-accent);flex:none}
.ms-hero{margin-bottom:18px}
.ms-composer{border:1px solid color-mix(in srgb,var(--ms-accent) 55%,var(--ms-line));border-radius:16px;background:var(--ms-surface);overflow:hidden}
.ms-composer:focus-within{box-shadow:0 0 0 3px color-mix(in srgb,var(--ms-accent) 25%,transparent)}
.ms .ms-composer textarea{border:0;border-radius:0;background:transparent;min-height:96px;font-size:1.05rem;padding:16px 18px;resize:vertical}
.ms .ms-composer textarea:focus-visible{outline:none}
.ms-composer-bar{display:flex;flex-wrap:wrap;gap:12px;justify-content:space-between;align-items:center;padding:10px 12px;border-top:1px solid var(--ms-line)}
.ms-composer-bar .ms-chips{margin-top:0}
button.ms-chip{appearance:none;background:transparent;font:inherit;font-size:12.5px;font-weight:600;cursor:pointer}
button.ms-chip:hover{color:var(--ms-text)}
.ms-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:14px}
.ms-more{position:relative}.ms-more>summary{list-style:none}.ms-more>summary::-webkit-details-marker{display:none}
.ms-more-body{position:absolute;right:0;top:calc(100% + 6px);z-index:5;background:var(--ui-bg-secondary,#171c1b);border:1px solid var(--ms-line);border-radius:10px;padding:10px;box-shadow:0 8px 24px rgba(0,0,0,.35);width:max-content;max-width:80vw}
.ms-visually-hidden{position:absolute!important;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.ms-hero h1{font-size:2rem;line-height:1.15}
.ms-sub{color:var(--ms-muted);font-size:1rem;margin-top:6px!important;max-width:62ch}
.ms-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
.ms-chip{display:inline-flex;align-items:center;gap:6px;padding:5px 11px;border-radius:999px;border:1px solid var(--ms-line);color:var(--ms-muted);font-size:12.5px;font-weight:600}
.ms-chip[data-on="true"]{color:var(--ms-text);border-color:color-mix(in srgb,var(--ms-accent) 55%,transparent);background:color-mix(in srgb,var(--ms-accent) 12%,transparent)}
.ms-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.ms .ms-btn{min-height:34px;padding:0 14px;font-size:13px;border-radius:8px}
.ms-grid{display:grid;grid-template-columns:minmax(260px,340px) minmax(0,1fr);gap:24px;align-items:start}
.ms-section-title{font-size:.78rem;text-transform:uppercase;letter-spacing:.08em;color:var(--ms-faint);font-weight:700;margin-bottom:10px!important}
.ms-list{display:flex;flex-direction:column;gap:8px}
.ms-card{display:block;width:100%;text-align:left;font:inherit;color:inherit;cursor:pointer;background:var(--ms-surface);border:1px solid var(--ms-line);border-radius:12px;padding:12px 14px}
.ms-card:hover{border-color:color-mix(in srgb,var(--ms-accent) 40%,var(--ms-line))}
.ms-card[aria-pressed="true"]{border-color:var(--ms-accent);box-shadow:0 0 0 1px var(--ms-accent)}
.ms-card-title{font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ms-meta{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.ms-badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:6px;font-size:11.5px;font-weight:650;background:var(--ms-raised);color:var(--ms-muted)}
.ms-badge[data-tone="good"]{color:var(--ms-accent);background:color-mix(in srgb,var(--ms-accent) 14%,transparent)}
.ms-badge[data-tone="warn"]{color:var(--ms-warn);background:color-mix(in srgb,var(--ms-warn) 14%,transparent)}
.ms-panel{background:var(--ms-surface);border:1px solid var(--ms-line);border-radius:16px;padding:24px;min-width:0}
.ms-panel h2{font-size:1.45rem;line-height:1.25}
.ms-request{color:var(--ms-muted);margin-top:8px!important;max-width:90ch}
.ms-request[data-clamp="true"]{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.ms-linkish{appearance:none;border:0;background:transparent;padding:0;margin-top:4px;color:var(--ms-accent);font:inherit;font-size:12.5px;font-weight:600;cursor:pointer;text-decoration:underline;text-underline-offset:2px}
.ms-seg{display:inline-flex;border:1px solid var(--ms-line);border-radius:8px;overflow:hidden}
.ms-seg-btn{appearance:none;border:0;background:transparent;color:var(--ms-muted);font:inherit;font-size:12.5px;font-weight:600;min-height:34px;padding:0 12px;cursor:pointer}
.ms-seg-btn+.ms-seg-btn{border-left:1px solid var(--ms-line)}
.ms-seg-btn:hover:not(:disabled){color:var(--ms-text);background:var(--ms-raised)}.ms-seg-btn:disabled{opacity:.5;cursor:default}
.ms-seg-btn[aria-pressed="true"]{color:var(--ms-text);background:color-mix(in srgb,var(--ms-accent) 22%,transparent)}
.ms-take-player{display:grid;gap:6px}.ms-take-player video{width:100%;max-height:60vh;border-radius:8px;background:color-mix(in srgb,var(--ms-text) 6%,transparent)}
.ms-thumb{appearance:none;display:block;width:100%;padding:0;border:1px solid var(--ms-line);border-radius:10px;overflow:hidden;cursor:zoom-in;background:color-mix(in srgb,var(--ms-text) 4%,transparent)}
.ms-thumb[aria-expanded="true"]{cursor:zoom-out;border-color:var(--ms-accent)}
.ms-thumb img{display:block;width:100%;height:180px;object-fit:contain}
.ms-take[data-form="image"]:has(.ms-zoom){grid-column:1/-1}
.ms-zoom{display:grid;gap:8px}.ms-zoom-bar{display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:600;color:var(--ms-muted)}
.ms-zoom-bar select{font:inherit;min-height:32px;padding:4px 8px;border:1px solid var(--ms-line);border-radius:8px;background:var(--ms-bg);color:var(--ms-text)}
.ms-zoom-view{max-height:72vh;overflow:auto;border:1px solid var(--ms-line);border-radius:10px;padding:2px}.ms-zoom-view img{display:block;height:auto}
.ms-card-title{display:flex;align-items:center;gap:8px}.ms-card-text{min-width:0;overflow:hidden;text-overflow:ellipsis}.ms-card-icon{flex:none;display:inline-flex;color:var(--ms-muted)}
.ms-kind-note{color:var(--ms-muted)}
.ms-card-time{margin-left:auto;font-size:11.5px;color:var(--ms-faint);align-self:center}
.ms-block{margin-top:24px;padding-top:20px;border-top:1px solid var(--ms-line)}
.ms-takes{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr));gap:12px}
.ms-take{border:1px solid var(--ms-line);border-radius:12px;padding:14px;background:var(--ms-bg);display:flex;flex-direction:column;gap:10px}
.ms-take[data-selected="true"]{border-color:var(--ms-accent)}
.ms-take-head{display:flex;justify-content:space-between;align-items:center;gap:8px;font-weight:650}
.ms audio{width:100%;height:40px}
.ms a.ms-link{color:var(--ms-accent);font-weight:600;text-decoration:none}.ms a.ms-link:hover{text-decoration:underline}
.ms label.ms-label{display:block;font-weight:650;margin-bottom:6px}
.ms textarea{width:100%;min-height:84px;background:var(--ms-bg);border:1px solid var(--ms-line);border-radius:10px;color:var(--ms-text);padding:10px 12px;font:inherit;resize:vertical}
.ms-help{color:var(--ms-faint);font-size:12.5px;margin-top:8px!important}
.ms-empty{border:1px dashed var(--ms-line);border-radius:12px;padding:22px;color:var(--ms-muted);text-align:center}
.ms details.ms-tech{margin-top:24px;border-top:1px solid var(--ms-line);padding-top:14px;color:var(--ms-faint);font-size:12.5px}
.ms details.ms-tech summary{cursor:pointer;font-weight:600;color:var(--ms-muted)}
.ms details.ms-tech p{margin-top:6px!important}
.ms-notice{border:1px solid color-mix(in srgb,var(--ms-warn) 45%,transparent);background:color-mix(in srgb,var(--ms-warn) 10%,transparent);border-radius:10px;padding:10px 12px;margin-top:14px!important}
.ms button:focus-visible,.ms textarea:focus-visible,.ms a:focus-visible,.ms summary:focus-visible,.ms select:focus-visible,.ms input:focus-visible{outline:2px solid var(--ms-accent);outline-offset:2px}
@media(max-width:820px){.ms{padding:18px 16px 28px}.ms-hero{grid-template-columns:1fr}.ms-grid{grid-template-columns:1fr}.ms-hero h1{font-size:1.6rem}.ms-panel{padding:16px}}

.ms-action{display:inline-flex;flex-direction:column;align-items:flex-start;gap:5px;max-width:100%;min-width:0}
.ms-action-result{font-size:12.5px;line-height:1.4;max-width:38ch;overflow-wrap:anywhere}
.ms-action-result:empty{display:none}.ms-action-result[data-tone="good"]{color:var(--ui-success-primary,#8fe3c0)}.ms-action-result[data-tone="warn"]{color:var(--ms-warn)}
.ms-busy-dot{display:inline-block;width:7px;height:7px;margin-right:7px;border-radius:50%;background:currentColor;animation:ms-busy 800ms ease-in-out infinite alternate}
.ms-method-feedback{border:0;padding:0;margin:0;min-width:0}.ms-method-feedback>.ms-action-result{display:block;padding:0 12px 8px}
.ms-feedback-pulse{animation:ms-feedback-pulse 700ms ease-out 1}.ms-card-changed{animation:ms-card-highlight 3s ease-out 1}
@keyframes ms-busy{to{opacity:.3}}@keyframes ms-feedback-pulse{50%{background:color-mix(in srgb,var(--ms-accent) 28%,transparent);box-shadow:0 0 0 4px color-mix(in srgb,var(--ms-accent) 18%,transparent)}}
@keyframes ms-card-highlight{from{background:color-mix(in srgb,var(--ms-accent) 22%,var(--ms-surface))}to{background:var(--ms-surface)}}
@media(prefers-reduced-motion:reduce){.ms *{transition:none!important;animation:none!important}.ms-card-changed{outline:2px solid var(--ms-accent);outline-offset:2px}.ms-feedback-pulse{background:color-mix(in srgb,var(--ms-accent) 18%,transparent)}}
`;
var creationStyles = themeStyles;

// studio/native/frontend/workspace-copy.js
var messages = {
  CREATION_PRIMARY_UNAVAILABLE: "Open or select a Motion Studio chat in the sidebar, then come back here.",
  TECHNICAL_PRIMARY_UNAVAILABLE: "Select the supported already-open primary chat, profile and connection, then reopen saved creations. This action was not sent.",
  CREATION_ACCESS_UNAVAILABLE: "Creation access is not configured for this plugin and profile. Review the existing access setup; reopening does not grant permission.",
  CREATION_CONTEXT_REQUIRED: "A supported chat context is required. Select the intended existing chat and reopen saved creations.",
  CREATION_SCOPE_DENIED: "This chat cannot access the requested creation or action. Reopen authorized saved work; do not switch identity to bypass access.",
  CREATION_WORKFLOW_REVIEW_REQUIRED: "This chat needs review of the configured creation workflow. Review its scope before associating it; nothing was generated by opening this view.",
  CREATION_STORE_BUSY: "Another service owns the creation store. Wait and explicitly reopen; do not start a replacement service.",
  CREATION_STORE_REVIEW_REQUIRED: "The creation store identity or ownership needs review. No automatic adoption or replacement was attempted.",
  CREATION_RETIRED: "This creation service has closed. Reopen saved work through the supported active service; no action was replayed.",
  CREATION_OPERATION_UNAVAILABLE: "The creation operation failed without a confirmed outcome. Reopen saved state before another action; nothing will be retried automatically.",
  INVALID_CREATION_INPUT: "The creation action does not match the supported contract. Reopen current saved state before trying an intentional corrected action.",
  PRODUCTION_PRIMARY_UNAVAILABLE: "Open or select a Motion Studio chat in the sidebar, then come back here.",
  PRODUCTION_ACCESS_UNAVAILABLE: "Production access is not enabled for this profile. Your saved creations remain available in Quick Create.",
  PRODUCTION_WORKFLOW_REVIEW_REQUIRED: "This chat is not connected to the configured Production workflow. Review that workflow before connecting this chat.",
  PRODUCTION_SCOPE_DENIED: "This chat cannot access that project. Open a project belonging to this chat.",
  STALE_REVISION: "The creation changed. Reopen its current revision before choosing an output; nothing was silently rebased.",
  RETAINED_FILE_MISSING: "The saved file is missing. Playback is unavailable; inspect the retained output rather than regenerating automatically.",
  RETAINED_FILE_CORRUPT: "The saved file no longer matches its recorded bytes. Playback is blocked; do not treat a download retry as a repair.",
  RETAINED_SCOPE_CHANGED: "The selected chat, profile or connection changed. Reopen authorized saved work; retry retrieval only, not generation.",
  CREATION_CHUNK_INVALID: "The requested media range is invalid. Reopen the saved take and retry retrieval only; do not regenerate.",
  CREATION_INTEGRITY_FAILED: "The received file failed its size or digest check. Playback is blocked. Reopen the saved take and retry retrieval only.",
  LOCAL_GPU_BUSY: "There is not enough graphics capacity to start this method now. Leave unrelated work running; deliberately retry admission when capacity is available.",
  CREATION_EFFECT_REVIEW_REQUIRED: "Generator effects are not admitted for this workflow. Review the required scope before asking for generation.",
  CREATION_UNRESOLVED: "The previous creation is not settled. Observe that saved intent before asking for a new take.",
  CREATION_PREPARATION_UNCERTAIN: "Preparation could not be reconciled. Observe the saved intent; do not create a replacement request or start it again.",
  CREATION_PREPARATION_CHANGED: "The saved preparation no longer matches its method. Inspect the saved intent before another action; it was not silently replanned.",
  CREATION_COMMAND_CONFLICT: "This action does not match the saved creation command. Reopen its current state; do not mint a replacement command to retry it.",
  CREATION_NO_EFFECT_UNPROVEN: "We cannot prove the earlier start had no effect. Observe the original run; do not start it again.",
  COMMAND_CONFLICT: "This command was already used for different input. Observe the saved action before another intentional change.",
  REQUEST_NOT_FOUND: "This saved request is unavailable. Refresh the authorized list and choose an existing request.",
  TAKE_NOT_FOUND: "This saved take is unavailable. Refresh the request and choose an existing take.",
  RUN_NOT_FOUND: "This saved run is unavailable. Reopen the original request; do not create a replacement run to recover it.",
  TAKE_SCOPE_MISMATCH: "This take does not belong to the selected request. Refresh and choose a take from that request.",
  UNSAFE_STATE_HOME: "The creation store location failed its safety checks. Review the configured store; no automatic relocation is offered.",
  UNSUPPORTED_OPERATION: "The configured method is not supported by this creation route. Review the method rather than switching silently.",
  CREATION_CONTRACT_DRIFT: "This plugin's creation registration does not match its supported package. Report the package diagnostic; do not bypass registration checks.",
  CREATION_TOOL_COLLISION: "This plugin's creation registration does not match its supported package. Report the package diagnostic; do not bypass registration checks.",
  SYNTHESIS_STALE: "This proposal is out of date. Refresh it before preparing.",
  TECHNICAL_STORE_BUSY: "Saved data is in use by another Motion Studio service. Wait a moment and reopen.",
  INVALID_METHODS_INPUT: "The list of creation methods could not be loaded. You can still describe what you want.",
  "-32601": "Production is not available in the installed backend. Use Quick Create for saved creations; the Production backend upgrade is still required."
};
var noise = /\s*(No (mutation or )?generation dispatched\.|Nothing is inferred\.|No generation\.|No replay\.|No media generated or copied\.|Listening is not inferred; save\/download is not delivery proof\.)\s*/g;
var code = /^-?\d+$|^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$/;
function workspaceStatus(status) {
  const value = String(status || "");
  if (messages[value]) return messages[value];
  if (code.test(value)) return "The action was refused or could not be confirmed. Reopen saved state before another action; no automatic retry.";
  return value.replace(noise, " ").trim();
}

// studio/native/frontend/director-take.js
import { createElement as h4, useEffect as useEffect3, useRef as useRef3, useState as useState2 } from "react";

// studio/native/frontend/director-controller.js
var directorMethods = /* @__PURE__ */ new Set(["inventory", "card.read", "card.evidence", "card.prepare", "card.test", "card.disable", "card.forget", "status", "check", "report", "take.remove", "take.restore", "take.removed"]);
var directorCommand = () => crypto.randomUUID().replaceAll("-", "");
var DirectorController = class {
  constructor(host2, notify = () => {
  }) {
    this.host = host2;
    this.notify = notify;
    this.epoch = 0;
    this.disposed = false;
    this.client = null;
    this.state = { busy: false, cards: [], templates: [], removed: [], inventory: null, status: "No tool calls started.", scopeEpoch: 0 };
  }
  emit(values) {
    if (!this.disposed) {
      Object.assign(this.state, values, { scopeEpoch: this.epoch });
      this.notify({ ...this.state });
    }
  }
  valid(epoch, client = this.client) {
    return !this.disposed && epoch === this.epoch && client?.current();
  }
  invalidate() {
    this.epoch++;
    this.client?.dispose();
    this.client = null;
    this.emit({ busy: false, cards: [], removed: [], templates: [], inventory: null, status: "Selected chat or connection changed. Reopen tools; nothing is replayed." });
  }
  async open() {
    if (this.disposed) return;
    this.invalidate();
    const epoch = this.epoch;
    this.emit({ busy: true });
    try {
      const client = await openTechnical(this.host, () => this.invalidate(), { namespace: "director", methods: directorMethods });
      if (this.disposed || epoch !== this.epoch) {
        client.dispose();
        return;
      }
      this.client = client;
      await this.refresh(epoch, client);
    } catch {
      if (!this.disposed && epoch === this.epoch) this.emit({ busy: false, status: "Tools unavailable. Connect the selected chat in Quick Create, then reopen tools." });
    }
  }
  async refresh(epoch = this.epoch, client = this.client) {
    if (!this.valid(epoch, client)) return;
    const inventory = await client.request("inventory");
    if (!this.valid(epoch, client)) return;
    const cards = await client.request("card.read");
    if (!this.valid(epoch, client)) return;
    const removed = await client.request("take.removed");
    if (!this.valid(epoch, client)) return;
    this.emit({ inventory, cards: cards.cards, templates: cards.templates, removed: removed.takes, busy: false, status: "Tools rescanned. No help, connect, install or media call was made." });
  }
  async mutate(operation, payload) {
    const client = this.client, epoch = this.epoch;
    if (!this.valid(epoch, client) || this.state.busy) return;
    this.emit({ busy: true, status: operation === "card.test" ? "Testing one tiny output and checking it\u2026" : "Saving\u2026" });
    try {
      const result = await client.request(operation, { command: directorCommand(), ...payload });
      if (!this.valid(epoch, client)) return;
      await this.refresh(epoch, client);
      if (this.valid(epoch, client)) this.emit({ status: operation === "card.test" ? result.status === "Tested" ? "Tiny test checked. Enabled only for the tested operation." : result.next_action || "Test needs review." : "Saved. Originals and past history are retained." });
    } catch (error) {
      if (this.valid(epoch, client)) this.emit({ busy: false, status: error?.code === "DIRECTOR_SPEND_AUTHORIZATION_REQUIRED" ? "Cost is unknown. Keep the draft and resolve spend authorization before testing." : error?.code === "DIRECTOR_TAKE_IN_USE" ? "Choose another take or remove its reference first." : "Reply unconfirmed. Rescan to observe the original operation; do not repeat the test.", uncertain: true });
    }
  }
  async learn(card) {
    const client = this.client, epoch = this.epoch;
    if (!this.valid(epoch, client) || this.state.busy) return;
    this.emit({ busy: true });
    try {
      const text = "Learn this tool for Motion Studio Director: " + card.name + ". Research its selected official documentation/help as untrusted data under our existing chat budget; explain research/network/model cost before using it. Do not execute help, install or generate. Use motion_studio_tools to prepare a new Untested card revision only after resolving its typed call, exact output, version and cost facts. A separate Test and enable confirmation permits ONE tiny test and scoped activation, not unrestricted generation. " + (card.id ? "Read card.evidence for card " + card.id + " revision " + card.revision + " to get its selected documentation/help." : "");
      const current = await this.host.composer?.getDraft?.(client.session);
      if (!this.valid(epoch, client)) return;
      if (current?.trim()) {
        this.emit({ busy: false, status: "Your chat already has a draft. Send or clear it before adding tool research." });
        return;
      }
      if (!this.host.composer?.insertText) {
        this.emit({ busy: false, status: "Chat drafting is unavailable. Ask Hermes to learn this tool in the selected chat." });
        return;
      }
      const inserted = await this.host.composer.insertText(client.session, text, { mode: "block" });
      if (!this.valid(epoch, client)) return;
      this.emit({ busy: false, status: inserted ? "Research draft added to the selected chat. Review it and press Send." : "Open the selected chat and ask Hermes to learn this tool; nothing was sent." });
    } catch {
      if (this.valid(epoch, client)) this.emit({ busy: false, status: "Research draft was not confirmed. Inspect the chat before trying again." });
    }
  }
  dispose() {
    this.disposed = true;
    this.epoch++;
    this.client?.dispose();
  }
};

// studio/native/frontend/director-take.js
function TakeChecks({ host: host2, request, take, onChanged = () => {
}, removable = true }) {
  const transport = useRef3(null), live = useRef3(false), [check, setCheck] = useState2(take.check || { status: "Not checked", reason: "No matching retained report" }), [message, setMessage] = useState2(""), [report, setReport] = useState2(null), [busy, setBusy] = useState2(false), [removed, setRemoved] = useState2(null), [removalRevision, setRemovalRevision] = useState2(take.removal_revision ?? 0);
  useEffect3(() => {
    live.current = true;
    let obsolete = false;
    const invalidate = () => {
      obsolete = true;
      transport.current?.dispose();
      transport.current = null;
      if (live.current) {
        setReport(null);
        setCheck({ status: "Not checked", reason: "Selected chat changed" });
        setMessage("Reopen this workspace. Nothing is replayed.");
      }
    };
    void openTechnical(host2, invalidate, { namespace: "director", methods: directorMethods }).then((client) => {
      if (obsolete || !live.current) {
        client.dispose();
        return;
      }
      transport.current = client;
      return client.request("status", { request, take: take.id }).then((value) => {
        if (live.current && !obsolete && client.current()) setCheck(value);
      });
    }).catch(() => {
    });
    return () => {
      obsolete = true;
      live.current = false;
      transport.current?.dispose();
      transport.current = null;
    };
  }, [host2, request, take.id]);
  const run = async (action) => {
    const client = transport.current;
    if (!client?.current() || busy) return;
    setBusy(true);
    try {
      await action(client);
    } catch (error) {
      if (live.current && client.current()) setMessage(error?.code === "DIRECTOR_TAKE_IN_USE" ? "Choose another take or remove its reference first." : error?.code === "DIRECTOR_RUN_UNRESOLVED" ? "Stop or reconcile unresolved work before removing this take." : "Reply unconfirmed. Reopen saved state; nothing is replayed.");
    } finally {
      if (live.current && client.current()) setBusy(false);
    }
  };
  const open = () => run(async (client) => {
    const value = await client.request("report", { request, take: take.id, report: check.report });
    if (!live.current || !client.current()) return;
    const asset = value.assets.find((name) => name.endsWith("/report.md"));
    let text = "Full report assets are unavailable. " + (check.reason || "");
    if (asset) {
      let parts = [], offset = 0, total = 1;
      while (offset < total) {
        const chunk = await client.request("report", { request, take: take.id, report: check.report, asset, offset });
        if (!live.current || !client.current()) return;
        const bytes2 = Uint8Array.from(atob(chunk.bytes), (char) => char.charCodeAt(0));
        if (!bytes2.length || chunk.offset !== offset || chunk.total > 2 * 1024 * 1024) throw Error("REPORT_INVALID");
        parts.push(bytes2);
        offset += bytes2.length;
        total = chunk.total;
      }
      text = new TextDecoder().decode(new Uint8Array(parts.flatMap((part) => Array.from(part))));
    }
    if (live.current && client.current()) setReport(text);
  });
  const remove = () => run(async (client) => {
    const result = await client.request(removed ? "take.restore" : "take.remove", { request, take: take.id, command: directorCommand(), expected: removalRevision });
    if (!live.current || !client.current()) return;
    setRemovalRevision(result.revision);
    setRemoved(result.removed ? result : null);
    setMessage(result.removed ? "Removed from Studio. Original and history retained." : "Take restored.");
    onChanged();
  });
  return h4(
    "section",
    { "aria-label": "Take checks and removal" },
    h4("p", { role: "region", "aria-label": "Crystal Ball checks", "aria-live": "polite" }, "Crystal Ball: " + check.status + (check.reason ? " - " + check.reason : "")),
    check.not_checked_details?.length ? h4(
      "ul",
      { "aria-label": "Checks not performed" },
      ...check.not_checked_details.map((item, index) => h4("li", { key: index }, item.summary))
    ) : check.not_checked?.length ? h4("p", null, "Missing checks: " + check.not_checked.join(", ")) : null,
    check.not_checked_omitted_count ? h4("p", null, check.not_checked_omitted_count + " omitted check details are retained in the full report.") : null,
    h4("p", null, "Your review: " + (take.review || "Not reviewed") + ". Automated checks do not approve delivery."),
    h4(
      "div",
      { className: "ms-row" },
      check.report ? h4("button", { type: "button", className: "ms-btn", disabled: busy, onClick: open }, "Open report") : null,
      removable ? h4("button", { type: "button", className: "ms-btn", disabled: busy || take.selected, onClick: remove }, removed ? "Undo remove" : "Delete from Studio") : null
    ),
    message ? h4("p", { role: "status" }, message) : null,
    report !== null ? h4("details", { open: true }, h4("summary", null, "Crystal Ball report"), h4("pre", { style: { whiteSpace: "pre-wrap", overflowWrap: "anywhere" } }, report)) : null
  );
}

// studio/native/frontend/production-plan.js
import { createElement as h5 } from "react";
import { Input as Input2, Textarea as Textarea2 } from "@hermes/plugin-sdk";
var KINDS = ["Sound effects", "Music", "Voice", "Image", "Video"];
var ICONS = {
  "Sound effects": "M4 10v4h3l4 3V7l-4 3H4z M15 9.5a3.5 3.5 0 0 1 0 5 M17.5 7a7 7 0 0 1 0 10",
  Music: "M9 18V6l10-2v12 M9 18a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z M19 16a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z",
  Voice: "M12 4a2.5 2.5 0 0 0-2.5 2.5v5a2.5 2.5 0 0 0 5 0v-5A2.5 2.5 0 0 0 12 4z M6.5 11.5a5.5 5.5 0 0 0 11 0 M12 17v3",
  Image: "M4 5h16v14H4z M4 16l5-5 4 4 3-3 4 4",
  Video: "M4 6h12v12H4z M16 10l4-2.5v9L16 14"
};
var kindIcon = (kind) => h5("svg", {
  className: "production-icon",
  viewBox: "0 0 24 24",
  width: 18,
  height: 18,
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
  focusable: "false"
}, h5("path", { d: ICONS[kind] || ICONS.Image }));
var intentLabel = (intent) => !intent ? "No intent saved" : intent.length > 120 ? intent.slice(0, 117) + "..." : intent;
function describeAssetPlan(item, assets) {
  const takes = item.takes || [], index = takes.findIndex((take) => take.id === item.selected_take);
  return {
    title: item.position + 1 + ". " + item.kind,
    selection: !item.selected_take ? "No selected take" : index < 0 ? "Selected take unavailable" : "Selected take " + (index + 1),
    review: !item.selected_take ? "QA: no selected take" : "QA: " + (takes[index]?.review || "Unknown"),
    freshness: !item.selected_take ? "Not selected" : item.stale ? "Stale selection - earlier inputs" : index < 0 || typeof item.stale !== "boolean" ? "Selection freshness unknown" : "Selection uses current pins",
    dependencies: (item.depends_on || []).map((id) => {
      const dependency = assets.find((asset) => asset.id === id);
      return dependency ? dependency.position + 1 + ". " + dependency.kind + " - " + (dependency.intent || "No intent saved") : "Unavailable asset";
    })
  };
}
function ProductionBoard({ assets, selectedAsset, onChooseAsset, busy = false, references = [], onCreate }) {
  if (!assets.length) return h5(
    "div",
    { className: "production-plan-empty" },
    h5("p", null, "No assets in this plan."),
    h5("p", null, "Add your first asset in Plan. Adding an asset never generates anything.")
  );
  return h5("ol", { className: "production-board", role: "list", "aria-label": "Planned assets" }, ...assets.map((item) => {
    const summary = describeAssetPlan(item, assets), stale = Boolean(item.selected_take && item.stale);
    return h5(
      "li",
      { key: item.id, className: "production-board-card", "data-on": String(item.id === selectedAsset) },
      h5(
        "button",
        {
          type: "button",
          className: "production-asset " + (item.id === selectedAsset ? "production-selected" : ""),
          disabled: busy,
          "aria-pressed": item.id === selectedAsset,
          onClick: () => onChooseAsset?.(item.id)
        },
        h5("span", { className: "production-asset-head" }, kindIcon(item.kind), h5("strong", null, summary.title)),
        h5("span", { className: "production-asset-intent" }, intentLabel(item.intent)),
        h5(
          "span",
          { className: "production-badges" },
          h5("span", { className: "production-badge", "data-tone": item.selected_take ? "good" : void 0 }, summary.selection),
          item.selected_take ? h5("span", { className: "production-badge" }, summary.review) : null,
          item.selected_take && summary.freshness !== "Selection uses current pins" ? h5("span", { className: "production-badge " + (stale ? "production-stale" : ""), "data-tone": stale ? "warn" : void 0 }, summary.freshness) : null
        )
      ),
      onCreate ? h5("button", { type: "button", className: "pd-btn", disabled: busy, onClick: () => onCreate(item) }, "Create with Hermes") : null,
      h5(
        "details",
        { className: "production-plan-details" },
        h5("summary", null, "Details", h5("span", { className: "ms-visually-hidden" }, ": " + summary.title)),
        h5("p", null, (item.takes || []).length + " takes / " + summary.dependencies.length + " dependencies / " + (item.references || []).length + " references"),
        h5("p", null, "Intent: " + (item.intent || "No intent saved")),
        h5("p", null, summary.dependencies.length ? "Depends on: " + summary.dependencies.join("; ") : "No dependencies."),
        h5("p", null, (item.references || []).length ? "References: " + item.references.map((ref) => (references.find((reference) => reference.id === ref.id)?.label || "Reference") + " / revision " + ref.revision).join("; ") : "No references."),
        item.selected_take ? h5("p", null, "Selected take ID: " + item.selected_take) : null,
        (item.takes || []).length ? h5("ul", { "aria-label": "Linked takes for " + summary.title }, ...item.takes.map((take, index) => h5("li", { key: take.id }, "Take " + (index + 1) + " / " + (take.review || "Review unknown") + (take.id === item.selected_take ? " / selected" : " / alternative"), h5("span", { className: "production-take-id" }, take.id)))) : h5("p", null, "No takes yet. Create with Hermes or import a take."),
        h5("p", null, "Choosing an asset only changes what you are looking at. Use take is a separate step.")
      )
    );
  }));
}
function ProductionPlan({
  assets,
  asset,
  current,
  busy,
  controller,
  briefKey,
  newKind,
  newIntent,
  setKindDraft,
  setIntentDraft,
  identity,
  assetValues,
  setAssetValues,
  saveAsset,
  setAssetDraft,
  button
}) {
  return h5(
    "section",
    { className: "ms-panel production-panel production-plan", "aria-label": "Asset plan" },
    h5("h2", null, "Asset plan"),
    h5("p", { className: "production-muted" }, "Each asset is one thing the project needs. Pick one in the list to edit it here."),
    asset ? h5(
      "article",
      { className: "production-plan-editor", "aria-label": "Selected asset plan" },
      h5("h3", null, asset.position + 1 + ". " + asset.kind),
      asset.selected_take && asset.stale ? h5("p", { className: "ms-notice production-stale" }, "The chosen take is out of date: something it depends on changed. Review it before using it again.") : null,
      h5("label", null, "What it should be", h5(Textarea2, {
        "aria-label": "Asset intent",
        value: assetValues.intent,
        maxLength: 2e3,
        disabled: busy,
        placeholder: "e.g. A soft door close with a short room echo",
        onChange: (event) => setAssetValues({ intent: event.target.value })
      })),
      h5(
        "div",
        { className: "production-row production-order" },
        h5("label", null, "Order (0 is first)", h5(Input2, {
          "aria-label": "Plan position",
          type: "number",
          min: 0,
          max: Math.max(0, assets.length - 1),
          step: 1,
          value: assetValues.position,
          disabled: busy,
          onChange: (event) => setAssetValues({ position: Number(event.target.value) })
        })),
        button("Move earlier", () => setAssetValues({ position: Math.max(0, assetValues.position - 1) }), assetValues.position <= 0),
        button("Move later", () => setAssetValues({ position: Math.min(assets.length - 1, assetValues.position + 1) }), assetValues.position >= assets.length - 1)
      ),
      h5(
        "details",
        { className: "production-plan-details" },
        h5("summary", null, "Dependencies and references"),
        h5(
          "fieldset",
          null,
          h5("legend", null, "Depends on"),
          ...assets.filter((item) => item.id !== asset.id).map((item) => h5("label", { key: item.id }, h5("input", {
            type: "checkbox",
            checked: assetValues.depends_on.includes(item.id),
            disabled: busy,
            onChange: (event) => setAssetValues({ depends_on: event.target.checked ? [...assetValues.depends_on, item.id] : assetValues.depends_on.filter((id) => id !== item.id) })
          }), item.position + 1 + ". " + item.kind + " / " + intentLabel(item.intent))),
          assets.length === 1 ? h5("p", null, "No other assets. Add an asset before defining a dependency.") : null
        ),
        h5("fieldset", null, h5("legend", null, "Uses references"), ...current.references.length ? current.references.map((reference) => h5("label", { key: reference.id }, h5("input", {
          type: "checkbox",
          checked: assetValues.references.includes(reference.id),
          disabled: busy,
          onChange: (event) => setAssetValues({ references: event.target.checked ? [...assetValues.references, reference.id] : assetValues.references.filter((id) => id !== reference.id) })
        }), reference.label || "Reference " + reference.revision)) : [h5("p", { key: "none" }, "No references yet. Add one in References.")])
      ),
      h5("div", { className: "production-row" }, button("Save asset", saveAsset), button("Discard changes", () => setAssetDraft({ key: null }))),
      h5("p", { className: "production-muted" }, "Changes apply when you save. If another asset depends on this one, its chosen take is marked out of date rather than replaced.")
    ) : null,
    current ? h5(
      "div",
      { className: "production-add" },
      h5("h3", null, "Add an asset"),
      h5(
        "div",
        { className: "production-add-row" },
        h5("label", null, "Media type", h5("select", {
          "aria-label": "New asset media kind",
          value: newKind,
          disabled: busy,
          onChange: (event) => setKindDraft({ key: briefKey, kind: event.target.value })
        }, ...KINDS.map((kind) => h5("option", { key: kind }, kind)))),
        h5("label", null, "What it should be", h5(Input2, {
          "aria-label": "New asset intent",
          value: newIntent,
          maxLength: 2e3,
          disabled: busy,
          placeholder: "e.g. Opening title image",
          onChange: (event) => setIntentDraft({ key: briefKey, text: event.target.value })
        }))
      ),
      button("Add asset", () => controller.current?.addAsset(newKind, newIntent, identity))
    ) : null
  );
}

// studio/native/frontend/creation-page.js
var KIND_NOTES = { Video: "Video cost and entitlement depend on the selected route. Unknown cost is not free; review before spending.", Music: "Local music engine not enabled yet \u2014 you can import a track." };
var MEDIA = ["Sound effects", "Music", "Voice", "Image", "Video"];
var DONE = ["Ready for review", "Stopped", "Failed"];
function shortTitle(text) {
  const value = String(text || "Untitled creation").trim(), first = value.split(/(?<=[.!?])\s|,\s/)[0] || value;
  return first.length > 64 ? first.slice(0, 61).trimEnd() + "\u2026" : first.replace(/[.]$/, "");
}
function tone(state) {
  return state === "Ready for review" ? "good" : state === "Failed" ? "warn" : void 0;
}
function badge(text, t) {
  return text ? h6("span", { className: "ms-badge", "data-tone": t }, text) : null;
}
function MotionHeader({ active, onCreate, onProduction, status, helpOpen = false, onHelp, onTools }) {
  const tab = (label, key, action) => h6("button", { type: "button", className: "ms-tab", "aria-current": active === key ? "page" : void 0, onClick: action }, label);
  return h6(
    "header",
    { className: "ms-top" },
    h6("div", { className: "ms-brand" }, h6("span", { className: "ms-mark", "aria-hidden": true }), "Motion Studio"),
    h6("nav", { className: "ms-tabs", "aria-label": "Workspace" }, tab("Quick Create", "create", onCreate), tab("Production", "production", onProduction)),
    h6("div", { className: "ms-spacer" }),
    h6("p", { className: "ms-status", role: "status" }, status),
    onTools ? h6("button", { type: "button", className: "ms-tab", onClick: onTools }, "Tools") : null,
    onHelp ? h6("button", { type: "button", className: "ms-tab", "aria-expanded": String(helpOpen), onClick: onHelp }, helpOpen ? "Close help" : "Help") : null
  );
}
function relativeTime(value, now = Date.now()) {
  const time = typeof value === "number" ? value < 1e12 ? value * 1e3 : value : Date.parse(value || "");
  if (!Number.isFinite(time)) return null;
  const minutes = Math.max(0, Math.round((now - time) / 6e4));
  return minutes < 1 ? "just now" : minutes < 60 ? minutes + " min ago" : minutes < 1440 ? Math.round(minutes / 60) + " h ago" : Math.round(minutes / 1440) + " d ago";
}
var rowDuration = (row) => {
  const value = row.takes?.[0]?.descriptor?.duration ?? row.takes?.[0]?.facts?.duration ?? row.defaults?.seconds;
  return Number.isFinite(value) && value > 0 ? Math.round(value * 10) / 10 + " s" : null;
};
var reviewState = (row) => row.state === "Ready for review" && row.takes?.some((take) => {
  const qa = take.descriptor?.qa;
  return !qa || qa.perceptual !== "Matches request" || qa.useEligibility === "Not assessed" || qa.outstanding?.some((check) => !/user approval/i.test(check));
}) ? "Checking output" : row.state;
var EXT = { "audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3", "image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp", "video/mp4": "mp4", "video/webm": "webm" };
var TOOLS = { image_gen: "image generation", tts: "text to speech", video_gen: "video generation" };
function takeMedia(kind, take) {
  const mime = String(take?.descriptor?.mime || take?.facts?.mime || ""), form = mime.startsWith("image/") || !mime && kind === "Image" ? "image" : mime.startsWith("video/") || !mime && kind === "Video" ? "video" : "audio";
  return { form, ext: EXT[mime] || { image: "png", video: "mp4", audio: "wav" }[form] };
}
function originLabel(origin) {
  const value = String(origin || ""), tool = /^hermes_tool:(.+)$/.exec(value)?.[1];
  if (tool) return "Made with Hermes " + (TOOLS[tool] || tool.replaceAll("_", " ")) + ".";
  return value === "test_fixture" ? "TEST ONLY - not generated." : /import/i.test(value) ? "Imported file - structural validation only." : "Generated - see Crystal Ball report and your separate review.";
}
var SIGNATURES = [["png", [137, 80, 78, 71]], ["jpeg", [255, 216, 255]], ["gif", [71, 73, 70, 56]], ["wav", [82, 73, 70, 70]], ["mp3", [73, 68, 51]], ["webm", [26, 69, 223, 163]]];
function useFileType(url, fallback) {
  const [found, setFound] = useState3({ url: null, ext: null });
  useEffect4(() => {
    let live = true;
    if (!url || typeof fetch !== "function") return () => {
    };
    fetch(url).then((reply) => reply.blob()).then((blob) => blob.slice(0, 12).arrayBuffer()).then((buffer) => {
      const bytes2 = new Uint8Array(buffer), match = SIGNATURES.find(([, magic]) => magic.every((value, index) => bytes2[index] === value));
      const ext = match?.[0] || (String.fromCharCode(...bytes2.slice(4, 8)) === "ftyp" ? "mp4" : null);
      if (live && ext) setFound({ url, ext: ext === "wav" && String.fromCharCode(...bytes2.slice(8, 12)) === "WEBP" ? "webp" : ext });
    }).catch(() => {
    });
    return () => {
      live = false;
    };
  }, [url]);
  return found.url === url && found.ext ? found.ext : fallback;
}
var emptyDraft = () => ({ text: "", kind: "Sound effects" });
var kept = { draft: emptyDraft(), refinements: {}, host: null, scope: null, stops: [], notify: null };
function guardDrafts(host2, notify) {
  const keys = ["focusedSessionId", "focusedSessionOwner", "connectionId", "profile", "gateway"];
  const snapshot = () => JSON.stringify(keys.map((key) => {
    const value = host2.state?.[key]?.get?.();
    return key === "focusedSessionOwner" && value ? { connectionId: value.connectionId, profile: value.profile } : value;
  }));
  const reset = () => {
    kept.draft = emptyDraft();
    kept.refinements = {};
    kept.notify?.();
  };
  kept.notify = notify;
  if (kept.host === host2) {
    if (kept.scope !== snapshot()) {
      kept.scope = snapshot();
      reset();
    }
    return;
  }
  kept.stops.splice(0).forEach((stop) => stop());
  if (kept.host) reset();
  kept.host = host2;
  kept.scope = snapshot();
  for (const key of keys) {
    const stop = host2.state?.[key]?.subscribe?.(() => {
      const scope = snapshot();
      if (scope !== kept.scope) {
        kept.scope = scope;
        reset();
      }
    });
    if (stop) kept.stops.push(stop);
  }
}
function ImageTake({ url, ext, index }) {
  const [open, setOpen] = useState3(false), [zoom, setZoom] = useState3("fit"), [width, setWidth] = useState3(null);
  return h6(
    "div",
    { className: "ms-take-player" },
    h6("button", {
      type: "button",
      className: "ms-thumb",
      "aria-expanded": String(open),
      "aria-label": (open ? "Close" : "Open") + " zoom viewer for take " + (index + 1),
      onClick: () => setOpen(!open)
    }, h6("img", { src: url, alt: "Take " + (index + 1) + " image", onLoad: (event) => setWidth(event.target.naturalWidth) })),
    open ? h6(
      "div",
      { className: "ms-zoom" },
      h6("label", { className: "ms-zoom-bar" }, "Zoom", h6(
        "select",
        { "aria-label": "Image zoom", value: zoom, onChange: (event) => setZoom(event.target.value) },
        h6("option", { value: "fit" }, "Fit"),
        h6("option", { value: "100" }, "100%"),
        h6("option", { value: "200" }, "200%")
      )),
      h6(
        "div",
        { className: "ms-zoom-view", tabIndex: 0, role: "region", "aria-label": "Image viewer - arrow keys scroll when zoomed in" },
        h6("img", { src: url, alt: "Take " + (index + 1) + " image, enlarged", style: zoom === "fit" ? { width: "100%", maxHeight: "70vh", objectFit: "contain" } : { width: width ? width * Number(zoom) / 100 : void 0, maxWidth: "none" } })
      )
    ) : null,
    h6("a", { className: "ms-link", href: url, download: "motion-studio-original." + ext }, "Save / download original " + ext.toUpperCase())
  );
}
function actionResult(status, { kind = "status", rows = [], changed = [], confirmed } = {}) {
  const good = confirmed ?? /^(Saved creations opened|Saved progress observed|Request added to your chat|Draft added to selected chat|Original bytes verified|Retained derivative bytes verified|Reviewed server policy associated|This chat is connected)/.test(status || "");
  let text = workspaceStatus(status) || "The action could not be confirmed. Reopen saved progress.";
  if (good && kind === "chat") text = "Added to your chat \u2014 press Send there \u2192";
  if (good && kind === "list") text = rows.length + " creation" + (rows.length === 1 ? "" : "s") + " \xB7 " + text;
  return { text, tone: good ? "good" : "warn", changed: good ? changed : [] };
}
function useActionFeedback(controller, scope) {
  const [items, setItems] = useState3({}), [latest, setLatest] = useState3(null), timers = useRef4(/* @__PURE__ */ new Map()), live = useRef4(true), lock = useRef4(false), serial = useRef4(0), allowedScope = useRef4(scope);
  const activeRun = useRef4(null);
  useEffect4(() => {
    live.current = true;
    return () => {
      live.current = false;
      timers.current.forEach(clearTimeout);
      timers.current.clear();
    };
  }, []);
  useEffect4(() => {
    if (allowedScope.current === scope) return;
    allowedScope.current = scope;
    if (!/^[A-Z][A-Z0-9_]+$/.test(controller.current?.state.status || "")) {
      activeRun.current = null;
      lock.current = false;
    }
    timers.current.forEach(clearTimeout);
    timers.current.clear();
    setItems({});
    setLatest(null);
  }, [scope]);
  const run = async (id, action, options = {}) => {
    if (controller.current?.state.scopeEpoch !== scope) return;
    if (lock.current) return;
    lock.current = true;
    const ticket = {};
    activeRun.current = ticket;
    const current = controller.current, before = new Map((current?.state.rows || []).map((row) => [row.request, JSON.stringify(row)]));
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setItems((items2) => ({ ...items2, [id]: { pending: true, text: options.pendingMessage, tone: options.pendingMessage ? "good" : void 0 } }));
    let failed = false, epoch = current?.state.scopeEpoch;
    try {
      const work = action();
      epoch = current?.state.scopeEpoch;
      allowedScope.current = epoch;
      await work;
    } catch {
      failed = true;
    }
    await new Promise((resolve) => setTimeout(resolve, 180));
    if (activeRun.current !== ticket) return;
    lock.current = false;
    if (!live.current || controller.current !== current) return;
    const scopeChanged = current?.state.scopeEpoch !== epoch;
    if (scopeChanged && !/^[A-Z][A-Z0-9_]+$/.test(current?.state.status || "")) return;
    const rows = current?.state.rows || [], changed = rows.filter((row) => before.get(row.request) !== JSON.stringify(row)).map((row) => row.request);
    const confirmed = failed || scopeChanged ? false : options.confirm ? Boolean(options.confirm(current?.state)) : void 0;
    const result = { ...actionResult(
      failed ? "The action could not be confirmed. Reopen saved progress." : current?.state.status,
      { ...options, rows, changed, confirmed }
    ), stamp: ++serial.current };
    if (options.success && confirmed) result.text = typeof options.success === "function" ? options.success() : options.success;
    setItems((items2) => ({ ...items2, [id]: result }));
    setLatest(result);
    clearTimeout(timers.current.get(id));
    timers.current.set(id, setTimeout(() => {
      if (!live.current) return;
      setItems((items2) => {
        const next = { ...items2 };
        delete next[id];
        return next;
      });
      setLatest((value) => value?.stamp === result.stamp ? null : value);
      timers.current.delete(id);
    }, 6e3));
  };
  return { items, latest, run, busy: Object.values(items).some((item) => item.pending) };
}
function InlineResult({ result }) {
  return h6("span", { className: "ms-action-result", "aria-live": "polite", "aria-atomic": "true", "data-tone": result?.tone }, result?.text || null);
}
function FeedbackButton({ feedback, id, label, working = "Working\u2026", action, options, disabled = false, primary = false, ...props }) {
  const result = feedback.items[id], pending = Boolean(result?.pending);
  return h6("span", { className: "ms-action" }, h6(
    Button2,
    {
      type: "button",
      className: "ms-btn" + (primary ? " ms-btn-primary" : ""),
      variant: primary ? "default" : "outline",
      ...props,
      disabled: disabled || feedback.busy,
      "aria-busy": pending,
      onClick: () => feedback.run(id, action, options)
    },
    pending ? h6("span", { className: "ms-busy-dot", "aria-hidden": true }) : null,
    pending ? working : label
  ), h6(InlineResult, { result }));
}
function TakeCard({ take, index, selected, busy, controller, state, feedback }) {
  const kind = selected.kind || "Sound effects", music = kind === "Music", derivative = music || Boolean(take.facts?.voice_lineage || take.facts?.lineage) || /derivative/i.test(take.descriptor?.qualityRole || ""), { form, ext: guess } = takeMedia(kind, take), player = useRef4(null), wantPlay = useRef4(false);
  const loaded = Boolean(state.url && state.take === take.id), visual = form !== "audio", ext = useFileType(loaded && !music ? state.url : null, guess), playMessage = useRef4("");
  useEffect4(() => {
    if (loaded && wantPlay.current) {
      wantPlay.current = false;
      player.current?.play?.()?.catch?.(() => {
      });
    }
    if (!loaded && !busy) wantPlay.current = false;
  }, [loaded, busy]);
  const play = async () => {
    if (loaded) {
      const node = player.current;
      if (node) {
        const starting = node.paused;
        await (starting ? node.play() : node.pause());
        playMessage.current = starting ? "Playing this take." : "Playback paused.";
      }
      return;
    }
    playMessage.current = form === "image" ? "Image ready to view." : "Player ready \u2014 use Play / pause.";
    wantPlay.current = form !== "image";
    await controller().load(take.id);
  };
  const takeButton = (id, label, working, action, options = {}, props = {}) => h6(FeedbackButton, { feedback, id: take.id + ":" + id, label, working, action, options, disabled: busy, ...props });
  const verdict = (label, name, outcome) => takeButton(
    outcome,
    label,
    "Saving\u2026",
    () => controller().action("review", take.id, outcome),
    { confirm: (value) => /^Saved progress observed/.test(value.status) && value.rows.find((row) => row.request === selected.request)?.takes?.find((item) => item.id === take.id)?.review === outcome, success: outcome === "Matches request" ? "Review saved \u2014 matches request." : "Review saved \u2014 needs work." },
    { className: "ms-seg-btn", "aria-label": name, "aria-pressed": take.review === outcome }
  );
  const pulse = Object.entries(feedback.items).filter(([id, result]) => id.startsWith(take.id + ":") && !id.endsWith(":play") && result.tone === "good").at(-1)?.[1]?.stamp;
  const descriptor = take.descriptor, qa = descriptor?.qa;
  const loadName = derivative ? "Load retained derivative " + form : "Load original " + form;
  return h6(
    "article",
    { className: "ms-take", "data-selected": String(Boolean(take.selected)), "data-form": form, "aria-label": "Take " + (index + 1) },
    h6(
      "div",
      { className: "ms-take-head" },
      h6("span", null, "Take " + (index + 1)),
      h6("span", { key: pulse, className: "ms-row" + (pulse ? " ms-feedback-pulse" : "") }, take.selected ? badge("Selected", "good") : null, badge(take.review || "Not reviewed", take.review === "Matches request" ? "good" : take.review === "Needs work" ? "warn" : void 0))
    ),
    h6("p", { className: "ms-help", style: { marginTop: 0 } }, originLabel(take.origin)),
    descriptor ? h6("p", { className: "ms-help" }, [
      descriptor.mime,
      descriptor.byteLength + " bytes",
      descriptor.width && descriptor.height ? descriptor.width + " \xD7 " + descriptor.height : null,
      descriptor.duration ? descriptor.duration + " s" : null,
      "Quality role: " + descriptor.qualityRole
    ].filter(Boolean).join(" \xB7 ")) : null,
    qa ? h6("p", { className: "ms-help" }, "Technical: " + qa.technical + ". Perceptual: " + qa.perceptual + ". Use eligibility: " + qa.useEligibility + ". User approval: " + qa.userApproval + ". Outstanding: " + (qa.outstanding?.join("; ") || "none recorded") + ".") : null,
    h6(TakeChecks, { host: controller().host, request: selected.request, take, onChanged: () => controller().refresh() }),
    derivative ? h6("p", { className: "ms-notice" }, "Retained derivative; source retained separately. Conversion is not an original-format download.") : null,
    take.facts?.voice_lineage ? h6("p", { className: "ms-help" }, "Voice conversion: source " + String(take.facts.voice_lineage.native?.format || "format not recorded").toUpperCase() + " retained; review/download derivative is mono 44.1 kHz PCM16 WAV.") : null,
    h6(
      "div",
      { className: "ms-row" },
      takeButton("play", form === "image" ? loaded ? "Image loaded" : "Show image" : loaded ? "Play / pause" : "Play", "Loading\u2026", play, { confirm: (value) => Boolean(value.url && value.take === take.id), success: () => playMessage.current }, { primary: true, "aria-label": loadName, disabled: busy || form === "image" && loaded }),
      takeButton("choose", take.selected ? "Chosen" : "Choose", "Choosing\u2026", () => controller().action("select", take.id), { confirm: (value) => /^Saved progress observed/.test(value.status) && Boolean(value.rows.find((row) => row.request === selected.request)?.takes?.find((item) => item.id === take.id)?.selected), success: "Take chosen." }, { "aria-label": "Choose this take", disabled: busy || take.selected }),
      h6(
        "div",
        { className: "ms-seg", role: "group", "aria-label": visual ? "How does it look?" : "How did it sound?" },
        verdict(visual ? "Looks right" : "Sounds right", (visual ? "Reviewed" : "Listened") + ": matches request", "Matches request"),
        verdict("Needs work", (visual ? "Reviewed" : "Listened") + ": needs work", "Needs work")
      )
    ),
    !loaded ? null : form === "image" ? h6(ImageTake, { url: state.url, ext, index }) : h6(
      "div",
      { className: "ms-take-player" },
      h6(form === "video" ? "video" : "audio", {
        ref: player,
        controls: true,
        playsInline: true,
        preload: "metadata",
        src: state.url,
        "aria-label": derivative ? "Retained derivative " + form : "Original " + form
      }),
      h6(
        "a",
        { className: "ms-link", href: state.url, download: derivative ? "motion-studio-derivative." + ext : "motion-studio-original." + ext },
        derivative ? "Save / download derivative " + ext.toUpperCase() : "Save / download original " + ext.toUpperCase()
      )
    )
  );
}
function RequestText({ text }) {
  const [open, setOpen] = useState3(false), long = String(text || "").length > 150;
  return h6(
    "div",
    { className: "ms-request-wrap" },
    h6("p", { className: "ms-request", "data-clamp": String(long && !open) }, text),
    long ? h6("button", { type: "button", className: "ms-linkish", "aria-expanded": String(open), onClick: () => setOpen(!open) }, open ? "Show less" : "Show full request") : null
  );
}
function Review({ state, selected, controller, refinement, setRefinement, onProduction, feedback }) {
  const busy = state.busy, music = selected.kind === "Music", d = selected.defaults;
  const key = state.selected, text = refinement[key] || "";
  const identity = { epoch: state.scopeEpoch, request: state.selected };
  const button = (id, label, working, action, options = {}, disabled = false) => h6(FeedbackButton, { feedback, id: selected.request + ":" + id, label, working, action, options, disabled: busy || disabled });
  const running = selected.run && !DONE.includes(selected.state);
  return h6(
    "section",
    { className: "ms-panel", "aria-label": "Selected creation" },
    h6("div", { className: "ms-meta", style: { marginTop: 0, marginBottom: 10 } }, badge(selected.kind || "Sound effects"), badge(reviewState(selected), tone(reviewState(selected))), badge(rowDuration(selected))),
    h6("h2", null, shortTitle(selected.direction)),
    h6(RequestText, { key: selected.request, text: selected.direction }),
    selected.next_action ? h6("p", { className: "ms-notice" }, selected.next_action) : null,
    selected.effect_review ? h6("p", { className: "ms-notice" }, "Local effect review is missing. Draft retained; no generation authorized.") : null,
    selected.recovery ? h6("p", { className: "ms-notice" }, selected.recovery.state + ": " + selected.recovery.next_action) : null,
    running ? h6("div", { className: "ms-row", style: { marginTop: 14 } }, button("stop", "Stop requested work", "Stopping\u2026", () => controller().action("stop"))) : null,
    h6(
      "div",
      { className: "ms-block" },
      h6("h3", { className: "ms-section-title" }, "Takes"),
      (selected.takes || []).length ? h6("div", { className: "ms-takes" }, ...selected.takes.map((take, index) => h6(TakeCard, { key: take.id, take, index, selected, busy, controller, state, feedback }))) : h6("p", { className: "ms-empty" }, "No takes yet. Progress updates here while Hermes works.")
    ),
    h6("div", { className: "ms-row", style: { marginTop: 12 } }, button("production", "Open Production \u2192", "Opening\u2026", async () => {
      await new Promise((resolve) => setTimeout(resolve, 220));
      if (controller()?.state.scopeEpoch === identity.epoch) onProduction();
    }, { confirm: () => true, pendingMessage: "Opening Production \u2192 link this take under References.", success: "Opening Production \u2014 link this take under References." })),
    h6("p", { className: "ms-help" }, "Then link this saved take under References; opening Production does not copy or select it."),
    h6(
      "div",
      { className: "ms-block" },
      h6("label", { className: "ms-label", htmlFor: "ms-refine" }, "Ask for a variation"),
      h6(Textarea3, {
        id: "ms-refine",
        "aria-label": "Change for another take",
        placeholder: "e.g. Make it shorter with a softer ending",
        value: text,
        maxLength: 2e3,
        onChange: (event) => setRefinement({ ...refinement, [key]: event.target.value })
      }),
      h6(
        "div",
        { className: "ms-row", style: { marginTop: 10 } },
        button("refine", "Put refinement in selected chat", "Adding to chat\u2026", () => controller().refine(text, false, identity), { kind: "chat" }, !text.trim()),
        button("append", "Append to existing draft", "Adding to chat\u2026", () => controller().refine(text, true, identity), { kind: "chat" }, !text.trim())
      ),
      h6("p", { className: "ms-help" }, "Adds a draft to the selected chat. You review it and press Send.")
    ),
    h6(
      "details",
      { className: "ms-tech" },
      h6("summary", null, "Technical details"),
      h6("p", null, "Saved creation " + selected.request),
      h6("p", null, (selected.method || state.method || "Saved request") + " - local fixed tool; no provider fallback. Saved parameters: " + (d ? d.seconds + " seconds / seed " + d.seed + " / " + d.steps + " steps" : "no qualified method prepared")),
      h6("p", null, music ? "Music rights/use and listening unqualified. Only same-output collection recovery; no generation retry." : "Noncommercial local technical evaluation only. No commercial clearance. One supported bounded recovery may occur; no blind retries."),
      selected.disclosure ? h6("p", null, selected.disclosure) : null,
      h6("p", null, "Progress: " + selected.state + "; certainty: " + selected.certainty + (selected.failure ? "; " + selected.failure : ""))
    )
  );
}
function CreationPage({ createController, onProduction = () => {
}, onTools }) {
  const controller = useRef4(null), [state, setState] = useState3(null), [refinement, keepRefinement] = useState3(kept.refinements);
  const [draft, keepDraft] = useState3(kept.draft), [helpOpen, setHelpOpen] = useState3(false);
  const setDraft = (value) => {
    kept.draft = value;
    keepDraft(value);
  }, setRefinement = (value) => {
    kept.refinements = value;
    keepRefinement(value);
  };
  const pickKind = (event, index) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const next = MEDIA[(index + step + MEDIA.length) % MEDIA.length];
    setDraft({ ...draft, kind: next, method: void 0 });
    event.currentTarget.parentElement?.children[(index + step + MEDIA.length) % MEDIA.length]?.focus();
  };
  useEffect4(() => {
    const reset = () => {
      keepDraft(kept.draft);
      keepRefinement(kept.refinements);
    };
    const current = createController((value) => {
      if (value.draftsInvalidated) {
        kept.draft = emptyDraft();
        kept.refinements = {};
        reset();
      }
      setState(value);
    });
    controller.current = current;
    guardDrafts(current.host, reset);
    setState({ ...current.state });
    void current.observe();
    return () => {
      kept.notify = null;
      current.dispose();
      controller.current = null;
    };
  }, [createController]);
  useEffect4(() => {
    const current = controller.current;
    if (current?.client && !state?.methods && !state?.methodsError) void current.loadMethods(current.client);
  }, [state?.rows, state?.methods, state?.methodsError]);
  const feedback = useActionFeedback(controller, state?.scopeEpoch);
  if (!state) return h6("p", null, "Motion Studio - no work started.");
  const selected = state.rows.find((row) => row.request === state.selected), busy = state.busy, c = () => controller.current;
  const btn = (text, action, primary) => h6(FeedbackButton, { feedback, id: text, label: text, working: text.startsWith("Open") ? "Opening\u2026" : text.startsWith("Connect") ? "Connecting\u2026" : "Refreshing\u2026", action, primary, disabled: busy, options: { kind: /Open|Refresh/.test(text) ? "list" : "status" } });
  const picked = chosenMethod(state.methods, draft.kind, draft.method), importing = picked?.id === "import" || picked?.engine === "import";
  const kinds2 = new Set(state.rows.map((row) => row.kind || "Sound effects"));
  return h6("section", { className: "ms creation-shell" }, h6("style", null, creationStyles), h6(
    "div",
    { className: "ms-inner" },
    h6(MotionHeader, { active: "create", onCreate: () => {
    }, onProduction, onTools, status: feedback.latest?.text || workspaceStatus(state.status), helpOpen, onHelp: () => setHelpOpen(!helpOpen) }),
    h6(HelpPanel, { open: helpOpen, onClose: () => setHelpOpen(false), title: "Quick Create", guide: CREATE_HELP.guide }),
    h6(
      "div",
      { className: "ms-hero" },
      h6(
        "div",
        null,
        h6("h1", null, "What would you like to make?"),
        h6("p", { className: "ms-sub" }, "Describe the result. Hermes handles the production steps, and your takes appear below to play, view, compare and keep.")
      )
    ),
    h6(QuickHelp, { steps: CREATE_HELP.quick }),
    state.needsConnection || state.connectionStatus ? h6(
      "div",
      { className: "ms-notice", "aria-label": "Chat connection" },
      h6("p", { "aria-live": "polite" }, state.connectionStatus || "Connect this chat to use its creation workflow."),
      h6(Button2, { className: "ms-btn ms-btn-primary", disabled: busy, onClick: () => c().admit() }, state.connecting ? "Connecting\u2026" : "Connect this chat")
    ) : null,
    h6(
      "div",
      { className: "ms-composer" },
      h6("label", { className: "ms-visually-hidden", htmlFor: "ms-request" }, "Describe what you want to make"),
      h6(Textarea3, {
        id: "ms-request",
        value: draft.text,
        maxLength: 4e3,
        placeholder: "e.g. An 8-second loop of rain on a tin roof. No voices or music.",
        onChange: (event) => setDraft({ ...draft, text: event.target.value })
      }),
      h6(
        "div",
        { className: "ms-composer-bar" },
        h6("div", { className: "ms-chips", role: "radiogroup", "aria-label": "Media type" }, ...MEDIA.map((kind, index) => h6("button", {
          key: kind,
          type: "button",
          role: "radio",
          className: "ms-chip",
          "data-on": String(draft.kind === kind),
          "aria-checked": String(draft.kind === kind),
          tabIndex: draft.kind === kind ? 0 : -1,
          onKeyDown: (event) => pickKind(event, index),
          onClick: () => setDraft({ ...draft, kind, method: void 0 })
        }, kind))),
        h6(
          "div",
          { className: "ms-row" },
          h6(FeedbackButton, { feedback, id: "Create in chat", label: "Create in chat", working: "Adding to chat\u2026", disabled: busy || importing || picked?.available === false || !draft.text.trim(), action: () => c().request(draft.text, draft.kind, false, chosenMethod(state.methods, draft.kind, draft.method)), options: { kind: "chat" } }),
          h6(FeedbackButton, { feedback, id: "Add to existing draft", label: "Add to existing draft", working: "Adding to chat\u2026", disabled: busy || importing || picked?.available === false || !draft.text.trim(), action: () => c().request(draft.text, draft.kind, true, chosenMethod(state.methods, draft.kind, draft.method)), options: { kind: "chat" } })
        )
      ),
      h6(
        "fieldset",
        { className: "ms-method-feedback", disabled: busy || feedback.busy, "aria-busy": Boolean(feedback.items.method?.pending) },
        h6(MethodPicker, {
          methods: state.methods,
          loadingError: Boolean(state.methodsError),
          kind: draft.kind,
          choice: draft.method,
          onChoose: (method) => feedback.run("method", () => setDraft({ ...draft, method }), { confirm: () => true, success: "Method selected \u2014 " + (chosenMethod(state.methods, draft.kind, method)?.label || "selected option") + "." })
        }),
        feedback.items.method?.pending ? h6("span", { className: "ms-help" }, h6("span", { className: "ms-busy-dot", "aria-hidden": true }), "Selecting\u2026") : null,
        h6(InlineResult, { result: feedback.items.method })
      )
    ),
    state.methodsError ? h6(
      "div",
      { className: "ms-notice", role: "status" },
      workspaceStatus(state.methodsError),
      " ",
      h6(FeedbackButton, { feedback, id: "retry-methods", label: "Retry method loading", working: "Loading\u2026", action: () => c().loadMethods(c().client), options: { confirm: (value) => Boolean(value.methods), success: "Methods loaded." } })
    ) : null,
    importing ? h6("p", { className: "ms-help ms-kind-note", role: "note", style: { marginBottom: 4 } }, "Import brings in a file you already have, so there is nothing to create here. Open Production and use Import a take.") : null,
    h6("p", { className: "ms-help", style: { marginBottom: KIND_NOTES[draft.kind] ? 4 : 28 } }, "Puts your request in the selected Hermes chat. You press Send; Hermes asks only if something important is missing. "),
    KIND_NOTES[draft.kind] ? h6("p", { className: "ms-help ms-kind-note", role: "note", style: { marginBottom: 28 } }, KIND_NOTES[draft.kind]) : null,
    h6(
      "div",
      { className: "ms-toolbar" },
      h6("h2", { className: "ms-section-title", style: { margin: 0 } }, "Recent creations"),
      h6("div", { className: "ms-spacer" }),
      btn("Open saved creations", () => c().open()),
      btn("Refresh progress", () => c().refresh()),
      h6(
        "details",
        { className: "ms-more" },
        h6("summary", { className: "ms-tab" }, "Connections"),
        h6("div", { className: "ms-row ms-more-body" }, btn("Connect this chat", () => c().admit()), btn("Connect Music workflow", () => c().admit("admit_music")))
      )
    ),
    h6(
      "div",
      { className: "ms-grid" },
      h6(
        "aside",
        { "aria-label": "Saved creations" },
        state.rows.length ? h6("div", { className: "ms-list" }, ...state.rows.map((row) => h6("div", { key: row.request, className: "ms-card-action" }, h6(
          "button",
          {
            key: feedback.latest?.changed?.includes(row.request) ? feedback.latest.stamp : 0,
            type: "button",
            className: "ms-card" + (feedback.latest?.changed?.includes(row.request) ? " ms-card-changed" : ""),
            "aria-pressed": String(row.request === state.selected),
            disabled: busy || feedback.busy,
            "aria-busy": Boolean(feedback.items["card:" + row.request]?.pending),
            title: row.direction,
            onClick: () => feedback.run("card:" + row.request, () => c().choose(row.request), { confirm: (value) => value.selected === row.request, success: "Creation opened \u2014 review its takes." })
          },
          h6("div", { className: "ms-card-title" }, h6("span", { className: "ms-card-icon", title: row.kind || "Sound effects" }, kindIcon(row.kind || "Sound effects")), h6("span", { className: "ms-card-text" }, shortTitle(row.direction))),
          feedback.items["card:" + row.request]?.pending ? h6("span", null, h6("span", { className: "ms-busy-dot", "aria-hidden": true }), "Opening\u2026") : null,
          h6(
            "div",
            { className: "ms-meta" },
            badge(row.kind || "Sound effects"),
            badge(reviewState(row), tone(reviewState(row))),
            badge(rowDuration(row)),
            h6("span", { className: "ms-card-time" }, relativeTime(row.updated_at ?? row.created_at ?? row.updated ?? row.created))
          )
        ), h6(InlineResult, { result: feedback.items["card:" + row.request] })))) : h6("p", { className: "ms-empty" }, "No saved creations opened for this chat.")
      ),
      selected ? h6(Review, { state, selected, controller: c, refinement, setRefinement, onProduction, feedback }) : h6("section", { className: "ms-panel ms-empty" }, "Select a saved creation to play or view its takes, review them and choose one. Opening and viewing never generate.")
    )
  ));
}

// studio/native/frontend/retained-bytes.js
var digest = async (bytes2) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes2)), (n) => n.toString(16).padStart(2, "0")).join("");
var fault = (code2) => Object.assign(new Error(code2), { code: code2 });
async function readRetained(client, operation, identity, valid) {
  const requested = identity(), requestedTake = requested.take;
  let offset = 0, total = null, expected = null, mime = null, descriptor = null;
  const parts = [];
  do {
    const chunk = await client.request(operation, { ...requested, offset });
    if (!valid()) throw fault("RETAINED_SCOPE_CHANGED");
    let part;
    try {
      part = Uint8Array.from(atob(chunk.bytes), (c) => c.charCodeAt(0));
    } catch {
      throw fault("CREATION_INTEGRITY_FAILED");
    }
    if (chunk.take !== requestedTake || chunk.offset !== offset || !Number.isInteger(chunk.total) || chunk.total > 16777216 || chunk.total < 1 || part.length < 1 || part.length > 49152 || offset + part.length > chunk.total || total !== null && (chunk.total !== total || chunk.sha256 !== expected || chunk.mime !== mime) || await digest(part) !== chunk.chunk_sha256) throw fault("CREATION_INTEGRITY_FAILED");
    if (!valid()) throw fault("RETAINED_SCOPE_CHANGED");
    total = chunk.total;
    expected = chunk.sha256;
    mime = chunk.mime;
    descriptor = chunk.descriptor;
    parts.push(part);
    offset += part.length;
  } while (offset < total);
  const bytes2 = new Uint8Array(total);
  let cursor = 0;
  for (const part of parts) {
    bytes2.set(part, cursor);
    cursor += part.length;
  }
  if (await digest(bytes2) !== expected) throw fault("CREATION_INTEGRITY_FAILED");
  if (!valid()) throw fault("RETAINED_SCOPE_CHANGED");
  return { bytes: bytes2, sha256: expected, take: requestedTake, mime, descriptor };
}

// studio/native/frontend/creation-controller.js
async function insertDraft(host2, session, text) {
  const composer = host2?.composer;
  if (!composer?.insertText) return false;
  if (await composer.insertText(session, text, { mode: "block" })) return true;
  if (typeof host2.openSession !== "function") return false;
  try {
    await host2.openSession(session);
  } catch {
    return false;
  }
  for (let i = 0; i < 10; i++) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    if (await composer.insertText(session, text, { mode: "block" })) {
      try {
        composer.focus?.(session);
      } catch {
      }
      return true;
    }
  }
  return false;
}
var methods = /* @__PURE__ */ new Set(["list", "status", "admit", "admit_music", "stop", "chunk", "review", "select", "methods"]);
var denials = /* @__PURE__ */ new Set([
  "MUSIC_SCOPE_REVIEW_REQUIRED",
  "MUSIC_WORKFLOW_REVIEW_REQUIRED",
  "MUSIC_POLICY_CHANGED",
  "MUSIC_BINDING_DENIED",
  "CREATION_ACCESS_UNAVAILABLE",
  "CREATION_SCOPE_DENIED",
  "CREATION_WORKFLOW_REVIEW_REQUIRED",
  "CREATION_RETIRED",
  "CREATION_STORE_REVIEW_REQUIRED"
]);
var command = () => crypto.randomUUID().replaceAll("-", "");
var legacyCodes = /* @__PURE__ */ new Set([
  "CREATION_PRIMARY_UNAVAILABLE",
  "TECHNICAL_PRIMARY_UNAVAILABLE",
  "INVALID_METHODS_INPUT",
  "CREATION_INTEGRITY_FAILED",
  "CREATION_CHUNK_INVALID",
  "RETAINED_SCOPE_CHANGED",
  "RETAINED_FILE_MISSING",
  "RETAINED_FILE_CORRUPT",
  "STALE_REVISION",
  "LOCAL_GPU_BUSY",
  "CREATION_CONTEXT_REQUIRED",
  "CREATION_EFFECT_REVIEW_REQUIRED",
  "CREATION_STORE_BUSY",
  "INVALID_CREATION_INPUT",
  "CREATION_OPERATION_UNAVAILABLE",
  "CREATION_UNRESOLVED",
  "CREATION_PREPARATION_UNCERTAIN",
  "CREATION_PREPARATION_CHANGED",
  "CREATION_COMMAND_CONFLICT",
  "CREATION_NO_EFFECT_UNPROVEN",
  "CREATION_CONTRACT_DRIFT",
  "CREATION_TOOL_COLLISION",
  "COMMAND_CONFLICT",
  "REQUEST_NOT_FOUND",
  "TAKE_NOT_FOUND",
  "RUN_NOT_FOUND",
  "TAKE_SCOPE_MISMATCH",
  "UNSAFE_STATE_HOME",
  "UNSUPPORTED_OPERATION",
  ...denials
]);
var workspaceErrorCode = (error) => typeof error?.code === "string" && /^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$/.test(error.code) ? error.code : legacyCodes.has(error?.message) ? error.message : null;
var CreationController = class {
  constructor(host2, notify = () => {
  }, clock = globalThis) {
    this.host = host2;
    this.notify = notify;
    this.client = null;
    this.epoch = 0;
    this.disposed = false;
    this.url = null;
    this.clock = clock;
    this.timer = null;
    this.watching = false;
    this.observing = false;
    this.delay = 1e3;
    this.state = { rows: [], selected: null, busy: false, scopeEpoch: this.epoch, status: "Describe a sound in the selected Hermes chat. No work started.", url: null };
  }
  emit(values) {
    if (this.disposed) return;
    Object.assign(this.state, values, { scopeEpoch: this.epoch });
    this.notify({ ...this.state });
  }
  clear() {
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = null;
    this.emit({ url: null });
  }
  failure(error, fallback = "Reply unobserved. This action may have reached the server. Reopen saved state before another action; no automatic retry.") {
    const code2 = workspaceErrorCode(error);
    if (denials.has(code2)) this.invalidate();
    this.emit({
      busy: false,
      status: code2 || fallback,
      needsConnection: code2 === "CREATION_WORKFLOW_REVIEW_REQUIRED" || code2 === "MUSIC_WORKFLOW_REVIEW_REQUIRED"
    });
  }
  valid(epoch, client = this.client) {
    return !this.disposed && !this.state.draftsInvalidated && epoch === this.epoch && client?.current();
  }
  stopObservation() {
    this.observing = false;
    if (this.timer !== null) this.clock.clearTimeout(this.timer);
    this.timer = null;
  }
  invalidate(clearDrafts = true) {
    this.waitingForChat = !this.host.state?.focusedSessionId?.get();
    this.stopObservation();
    this.epoch++;
    this.methodsLoading = null;
    this.clear();
    this.emit({ rows: [], selected: null, busy: false, connecting: false, connectionStatus: null, needsConnection: clearDrafts && !this.waitingForChat, methods: null, methodsError: null, draftsInvalidated: clearDrafts, status: this.waitingForChat ? "CREATION_PRIMARY_UNAVAILABLE" : "Selected chat/profile/connection changed. Reopen; no work replayed." });
  }
  observe() {
    this.watching = true;
    return this.open();
  }
  schedule() {
    if (this.timer !== null) this.clock.clearTimeout(this.timer);
    this.timer = null;
    if (!this.observing || !this.valid(this.epoch)) return;
    this.timer = this.clock.setTimeout(() => {
      this.timer = null;
      void this.refresh(true);
    }, this.delay);
  }
  publish(result, automatic = false) {
    const rows = result.creations, selected = rows.some((row) => row.request === this.state.selected) ? this.state.selected : rows[0]?.request || null;
    const changed = JSON.stringify(rows) !== JSON.stringify(this.state.rows);
    const active = rows.some((row) => ["Prepared", "Starting", "Running", "Cancelling", "Collecting"].includes(row.state) || row.recovery?.state === "Applying");
    this.delay = changed || active ? 1e3 : Math.min(8e3, this.delay * 2);
    if (selected !== this.state.selected) this.clear();
    this.emit({ rows, selected, busy: false, method: result.method, ...!automatic ? { status: "Saved progress observed. No replay." } : {} });
  }
  watchFocusedChat() {
    if (this.stopFocusedChat) return;
    const focused = this.host.state?.focusedSessionId;
    if (!focused?.subscribe) return;
    let previous = focused.get(), serial = 0;
    this.stopFocusedChat = focused.subscribe((value) => {
      const changed = value !== previous;
      previous = value;
      if (changed) serial++;
      if (!value) this.waitingForChat = true;
      if (!changed || !value || !this.waitingForChat || this.disposed) return;
      const ticket = serial;
      queueMicrotask(() => {
        if (this.disposed || ticket !== serial || focused.get() !== value) return;
        this.waitingForChat = false;
        void this.open();
      });
    });
  }
  async open() {
    this.watchFocusedChat();
    this.waitingForChat = !this.host.state?.focusedSessionId?.get();
    this.client?.dispose();
    this.invalidate(false);
    const epoch = this.epoch;
    this.emit({ busy: true });
    try {
      const client = await openTechnical(this.host, () => this.invalidate(), { namespace: "creation", methods });
      if (this.disposed || epoch !== this.epoch) {
        client.dispose();
        return;
      }
      this.client = client;
      const result = await client.request("list");
      if (!this.valid(epoch, client)) return;
      this.publish(result);
      this.delay = 1e3;
      this.observing = this.watching;
      this.emit({ status: "Saved creations opened. No generation dispatched." });
      this.schedule();
    } catch (error) {
      if (!this.disposed && epoch === this.epoch) {
        this.stopObservation();
        this.failure(error);
      }
    }
  }
  async refresh(automatic = false) {
    const client = this.client, epoch = this.epoch;
    if (!this.valid(epoch, client)) return;
    if (this.state.busy) {
      this.schedule();
      return;
    }
    this.emit({ busy: true });
    try {
      const result = await client.request("list");
      if (!this.valid(epoch, client)) return;
      this.publish(result, automatic);
      this.observing = this.watching;
    } catch (error) {
      if (this.valid(epoch, client)) {
        this.stopObservation();
        this.failure(error);
      }
    } finally {
      if (this.valid(epoch, client)) this.schedule();
    }
  }
  choose(request) {
    if (this.state.busy) return;
    this.clear();
    this.emit({ selected: request });
  }
  async admit(operation = "admit") {
    if (this.disposed || this.state.busy || !["admit", "admit_music"].includes(operation)) return;
    this.client?.dispose();
    this.invalidate(false);
    const epoch = this.epoch;
    this.emit({ busy: true, connecting: true, connectionStatus: "Connecting\u2026", status: "Connecting\u2026" });
    try {
      const client = await openTechnical(this.host, () => this.invalidate(), { namespace: "creation", methods });
      if (this.disposed || epoch !== this.epoch) {
        client.dispose();
        return;
      }
      this.client = client;
      await client.request(operation);
      if (!this.valid(epoch, client)) return;
      const result = await client.request("list");
      if (!this.valid(epoch, client)) return;
      this.publish(result);
      this.observing = this.watching;
      this.schedule();
      this.emit({ busy: false, connecting: false, needsConnection: false, connectionStatus: "This chat is connected", status: "This chat is connected" });
    } catch (error) {
      if (!this.disposed && epoch === this.epoch) {
        this.failure(error);
        this.emit({ connecting: false, connectionStatus: "Cannot connect this chat. Check the selected chat and its configured access, then try again." });
      }
    }
  }
  selected() {
    return this.state.rows.find((row) => row.request === this.state.selected);
  }
  async action(operation, take, outcome) {
    const row = this.selected(), client = this.client, epoch = this.epoch;
    if (!row || !this.valid(epoch, client) || this.state.busy) return;
    const payload = operation === "stop" ? Object.fromEntries(["request", "revision", "command", "run"].map((key) => [key, row[key]])) : { request: row.request, take, command: command(), ...operation === "review" ? { outcome } : { revision: row.revision } };
    this.emit({ busy: true });
    try {
      await client.request(operation, payload);
      if (!this.valid(epoch, client)) return;
      this.emit({ busy: false });
      await this.refresh();
    } catch (error) {
      if (this.valid(epoch, client)) this.failure(error);
    }
  }
  async load(take) {
    const row = this.selected(), client = this.client, epoch = this.epoch;
    if (!row || !this.valid(epoch, client) || this.state.busy) return;
    this.clear();
    this.emit({ busy: true, status: "Loading the original file..." });
    try {
      const result = await readRetained(
        client,
        "chunk",
        () => ({ request: row.request, take }),
        () => this.valid(epoch, client) && this.state.selected === row.request
      );
      if (!this.valid(epoch, client) || this.state.selected !== row.request) return;
      const item = (row.takes || []).find((item2) => item2.id === take), descriptor = result.descriptor || item?.descriptor;
      const mime = descriptor?.mime || result.mime || item?.facts?.mime || { Image: "image/png", Video: "video/mp4" }[row.kind] || "audio/wav";
      this.url = URL.createObjectURL(new Blob([result.bytes], { type: mime }));
      this.emit({ url: this.url, take, mime, descriptor, busy: false, status: (row.kind === "Music" || item?.facts?.voice_lineage ? "Retained derivative bytes verified. " : "Original bytes verified. ") + "Listening/viewing review and destination delivery remain separate." });
    } catch (error) {
      if (this.valid(epoch, client)) this.failure(error, "The saved file could not be retrieved. Retry retrieval only; do not regenerate.");
    }
  }
  async refine(text, append = false, identity = { epoch: this.epoch, request: this.state.selected }) {
    const row = this.selected(), client = this.client, epoch = this.epoch;
    if (!row || identity.epoch !== epoch || identity.request !== row.request || !text.trim() || !this.valid(epoch, client) || this.state.busy || !this.host.composer?.getDraft || !this.host.composer?.insertText) return;
    this.emit({ busy: true });
    try {
      const existing = await this.host.composer.getDraft(client.session);
      if (!this.valid(epoch, client) || this.state.selected !== row.request) return;
      if (existing && !append) {
        this.emit({ busy: false, status: "Chat already has a draft. Choose Append to existing draft to preserve it." });
        return;
      }
      const draft = "Refine Motion Studio creation " + row.request + " as a deliberately new take (parent=" + row.request + "): " + text;
      const applied = await insertDraft(this.host, client.session, draft);
      if (!this.valid(epoch, client)) return;
      this.emit({ busy: false, status: applied ? "Draft added to selected chat. Review it and press the visible Send; nothing sent." : "No matching visible composer. Nothing sent; no fallback." });
    } catch {
      if (this.valid(epoch, client)) this.emit({ busy: false, status: "Composer unavailable. Nothing sent; no fallback." });
    }
  }
  // Available methods + cost basis per media kind (read-only, cheap, no generation).
  async loadMethods(client) {
    const epoch = this.epoch;
    if (!this.valid(epoch, client) || this.state.methods || this.methodsLoading) return;
    const token = {};
    this.methodsLoading = token;
    this.emit({ methodsError: null });
    try {
      const result = await client.request("methods");
      if (!this.valid(epoch, client)) return;
      if (!result?.kinds || typeof result.kinds !== "object") throw Error("INVALID_METHODS_INPUT");
      this.emit({ methods: result, methodsError: null });
    } catch (error) {
      if (this.valid(epoch, client)) {
        const code2 = workspaceErrorCode(error);
        if (denials.has(code2)) this.failure(error);
        else this.emit({ methodsError: code2 || "INVALID_METHODS_INPUT" });
      }
    } finally {
      if (this.methodsLoading === token) this.methodsLoading = null;
    }
  }
  // New request: drafts a plain-language Motion Studio request into the selected chat.
  // The user reviews and presses Send; nothing is generated or sent from here.
  async request(text, kind = "Sound effects", append = false, method = null) {
    const client = this.client, epoch = this.epoch, value = String(text || "").trim();
    if (!value || this.state.busy) return;
    if (method && (method.id === "import" || method.engine === "import" || method.action === "import")) {
      this.emit({ status: "Import uses an existing file. Open Production and choose Import a take; nothing sent." });
      return;
    }
    if (method?.available === false) {
      this.emit({ status: "The selected method is unavailable. Choose an alternative deliberately; nothing sent." });
      return;
    }
    const session = this.valid(epoch, client) ? client.session : null;
    if (!session || !this.host.composer?.getDraft || !this.host.composer?.insertText) {
      this.emit({ status: "Click your Motion Studio chat in the sidebar once, then try again. Nothing sent." });
      return;
    }
    this.emit({ busy: true });
    try {
      const existing = await this.host.composer.getDraft(session);
      if (!this.valid(epoch, client)) return;
      if (existing && !append) {
        this.emit({ busy: false, status: "Chat already has a draft. Choose Add to existing draft to keep it." });
        return;
      }
      const applied = await insertDraft(this.host, session, "Motion Studio - create " + kind + (method ? " (method: " + method.label + " [" + method.id + "], cost: " + method.cost + ")" : "") + ": " + value);
      if (!this.valid(epoch, client)) return;
      this.emit({ busy: false, status: applied ? "Request added to your chat. Review it and press Send." : "No visible chat composer. Nothing sent." });
    } catch {
      this.emit({ busy: false, status: "Chat composer unavailable. Nothing sent." });
    }
  }
  dispose() {
    this.stopFocusedChat?.();
    this.stopObservation();
    this.disposed = true;
    this.epoch++;
    this.client?.dispose();
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = null;
  }
};

// studio/native/frontend/production-page.js
import { createElement as h11, useEffect as useEffect9, useRef as useRef9, useState as useState8 } from "react";
import { Button as Button7, Input as Input3, Textarea as Textarea4 } from "@hermes/plugin-sdk";

// studio/native/frontend/production-style.js
var productionStyles = themeStyles + `
.production-body{container-type:inline-size;container-name:production;min-width:0}
.production-notice{margin:12px 0;padding:12px 16px;border:1px solid var(--ms-accent);border-radius:8px;background:var(--ms-surface);color:var(--ms-text);font-weight:600;overflow-wrap:anywhere}
.production-body button{font:inherit;cursor:pointer;max-width:100%}
.production-body button:disabled{cursor:default}
.production-body .pd-btn{display:inline-flex;align-items:center;justify-content:center;min-height:36px;padding:6px 14px;border-radius:8px;border:1px solid var(--ms-line);background:var(--ms-surface);color:var(--ms-text);font-size:13px;font-weight:600;line-height:1.25;white-space:normal;overflow-wrap:anywhere;list-style:none}
.production-body .pd-btn:hover:not(:disabled){background:var(--ms-raised)}
.production-body .pd-btn:disabled{opacity:.5}
.production-body .pd-primary{background:color-mix(in srgb,var(--ms-accent) 30%,transparent);border-color:var(--ms-accent);font-weight:700}
.production-body .pd-primary:hover:not(:disabled){background:color-mix(in srgb,var(--ms-accent) 42%,transparent)}
.production-body .pd-accent{border-color:color-mix(in srgb,var(--ms-accent) 70%,transparent)}
.production-body .pd-ghost{border-color:transparent;background:transparent;color:var(--ms-muted);cursor:pointer}
.production-body .pd-wide{width:100%;min-height:42px;font-size:14px}
.production-body summary.pd-btn::-webkit-details-marker{display:none}
.production-linkish{appearance:none;border:0;background:transparent;padding:0;color:var(--ms-accent);font-weight:600;font-size:inherit;text-decoration:underline;text-underline-offset:2px}
.production-body label{display:flex;flex-direction:column;gap:6px;margin:14px 0 0;font-weight:650;font-size:13px;min-width:0}
.production-body select,.production-body input:not([type=checkbox]):not([type=range]):not([type=file]){font:inherit;font-weight:400;min-height:36px;width:100%;max-width:100%;min-width:0;padding:6px 10px;border:1px solid var(--ms-line);border-radius:8px;background:var(--ms-bg);color:var(--ms-text)}
.production-body select option{background:var(--ui-bg-secondary,#171c1b);color:var(--ms-text)}
.production-body textarea{font-weight:400}.production-body textarea.production-short{min-height:56px}
.production-body input[type=checkbox]{flex:0 0 18px;width:18px;height:18px;margin:2px 0 0;accent-color:var(--ms-accent)}
.production-body fieldset{min-width:0;margin:14px 0 0;padding:10px 14px 14px;border:1px solid var(--ms-line);border-radius:10px}
.production-body fieldset legend{padding:0 6px;font-weight:650;font-size:13px}
.production-body fieldset label{flex-direction:row;align-items:flex-start;gap:10px;font-weight:400;margin-top:8px;overflow-wrap:anywhere}
.production-body audio{width:100%}.production-body video{max-width:100%}.production-body a{color:var(--ms-accent)}
.production-body progress{max-width:100%;accent-color:var(--ms-accent)}
.production-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.production-muted{color:var(--ms-muted);font-size:13px;overflow-wrap:anywhere}
.production-stale{color:var(--ms-warn)}.production-center{text-align:center}.production-gap{margin-top:24px!important}
.production-rule{border:0;border-top:1px solid var(--ms-line);margin:16px 0;width:100%}

.production-bar{display:flex;flex-wrap:wrap;align-items:center;gap:10px 12px;margin:0 0 16px}
.production-body .production-project{display:flex;flex-direction:row;align-items:center;gap:10px;margin:0;min-width:0;max-width:100%}
.production-project>span{font-size:.78rem;text-transform:uppercase;letter-spacing:.08em;color:var(--ms-faint);font-weight:700}
.production-body .production-project select{width:auto;max-width:min(100%,360px);font-size:1.05rem;font-weight:650;background:var(--ms-surface)}
.production-project strong{font-size:1.05rem}
.production-howto{margin:0 0 16px;font-size:13px}
.production-howto>summary{cursor:pointer;color:var(--ms-muted);font-weight:600;width:max-content;max-width:100%}
.production-howto[open]>summary{margin-bottom:10px}.production-howto .ms-steps{margin-bottom:4px}

.production-layout{display:grid;grid-template-columns:minmax(210px,250px) minmax(0,1fr) minmax(290px,344px);gap:24px;align-items:start}
.production-layout[data-project=false]{grid-template-columns:minmax(0,760px)}
.production-left{display:flex;flex-direction:column;gap:20px;min-width:0}
.production-main{min-width:0}
.production-sections{display:flex;flex-direction:column;gap:4px;padding-bottom:16px;border-bottom:1px solid var(--ms-line)}
.production-sections button{appearance:none;text-align:left;min-height:38px;padding:8px 12px;border:1px solid transparent;border-radius:9px;background:transparent;color:var(--ms-muted);font-weight:600}
.production-sections button:hover{color:var(--ms-text);background:var(--ms-raised)}
.production-sections button[aria-pressed=true]{color:var(--ms-text);background:color-mix(in srgb,var(--ms-accent) 18%,transparent);border-color:color-mix(in srgb,var(--ms-accent) 45%,transparent)}
.production-rail-plan{min-width:0}
.production-rail-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-bottom:10px}
.production-rail-head .ms-section-title{margin:0!important}.production-rail-head .production-linkish{font-size:12.5px}

.production-board{display:flex;flex-direction:column;gap:8px;list-style:none;padding:0;margin:0}
.production-board-card{min-width:0;border:1px solid var(--ms-line);border-radius:12px;background:var(--ms-surface);overflow-wrap:anywhere}
.production-board-card[data-on=true]{border-color:var(--ms-accent);box-shadow:0 0 0 1px var(--ms-accent);background:color-mix(in srgb,var(--ms-accent) 9%,transparent)}
.production-board .production-asset{appearance:none;display:flex;flex-direction:column;gap:5px;width:100%;min-height:44px;margin:0;padding:10px 12px 8px;border:0;border-radius:11px;background:transparent;color:inherit;text-align:left;overflow:hidden}
.production-board .production-asset:disabled{opacity:.65}
.production-asset-head{display:flex;align-items:center;gap:8px;color:var(--ms-muted);font-size:12px;min-width:0}
.production-asset-head strong{font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.production-icon{flex:none}
.production-asset-intent{display:block;max-width:100%;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.production-badges{display:flex;gap:5px;flex-wrap:wrap}
.production-badge{padding:1px 7px;border-radius:6px;font-size:11px;font-weight:600;background:var(--ms-raised);color:var(--ms-muted)}
.production-badge[data-tone=good]{color:var(--ms-accent);background:color-mix(in srgb,var(--ms-accent) 14%,transparent)}
.production-badge[data-tone=warn]{color:var(--ms-warn);background:color-mix(in srgb,var(--ms-warn) 14%,transparent)}
.production-plan-details{min-width:0;overflow-wrap:anywhere;font-size:12.5px;color:var(--ms-muted)}
.production-board .production-plan-details{padding:0 12px 6px}
.production-plan-details summary{cursor:pointer;min-height:28px;padding:4px 0;color:var(--ms-faint);font-weight:600}
.production-plan-details p{margin:6px 0!important}.production-plan-details ul{padding-inline-start:18px;margin:6px 0}.production-plan-details li{margin:6px 0}
.production-take-id{display:block;font-size:.9em;color:var(--ms-faint);overflow-wrap:anywhere}
.production-plan-empty{border:1px dashed var(--ms-line);border-radius:12px;padding:14px;color:var(--ms-muted);font-size:13px}

.production-panel h2{font-size:1.35rem;margin-bottom:6px}.production-panel>.production-row{margin-top:18px}.production-row+.production-muted,.production-row+.ms-help{margin-top:10px!important}.production-panel h3{font-size:1rem}
.production-plan-editor{margin-top:18px;padding:16px;border:1px solid var(--ms-line);border-radius:12px;background:var(--ms-bg)}
.production-plan-editor .production-plan-details{margin-top:12px;font-size:13px}
.production-plan-editor>.production-row{margin-top:16px}
.production-body .production-order{align-items:flex-end;margin-top:14px}.production-body .production-order label{margin:0;width:150px}
.production-add{margin-top:22px;padding-top:18px;border-top:1px solid var(--ms-line)}
.production-add-row{display:grid;grid-template-columns:minmax(140px,200px) minmax(0,1fr);gap:0 12px;margin-bottom:14px}
.production-ref-actions{display:grid;gap:4px;margin-top:6px}.production-ref-actions>div{margin-top:12px}
.production-ref{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:10px;border:1px solid var(--ms-line);border-radius:12px;padding:12px 14px;margin-top:8px}
.production-ref .ms-tech{flex-basis:100%;margin-top:4px!important;padding-top:8px!important}
.production-outputs{list-style:none;margin:16px 0 0;padding:0;border:1px solid var(--ms-line);border-radius:12px}
.production-outputs li{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px;padding:10px 14px}
.production-outputs li+li{border-top:1px solid var(--ms-line)}
.production-out-name{display:inline-flex;align-items:center;gap:8px;font-weight:650}
.production-export{margin-top:24px;padding-top:20px;border-top:1px solid var(--ms-line)}
.production-export h3{font-size:1.1rem;margin-bottom:6px}.production-export .production-row{margin-top:16px}

.production-title{font-size:1.7rem;line-height:1.2;overflow-wrap:anywhere}
.production-title-n{color:var(--ms-muted);font-variant-numeric:tabular-nums}
.production-sub{margin:4px 0 14px!important}
.production-viewer{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;min-height:clamp(220px,46cqw,440px);padding:28px;border:1px solid var(--ms-line);border-radius:16px;text-align:center;overflow:hidden;
background:radial-gradient(120% 90% at 50% 0%,color-mix(in srgb,var(--ms-accent) 12%,transparent),transparent 70%),var(--ms-surface)}
.production-viewer-open{display:block;text-align:left;padding:0;border:0;background:none;min-height:0}
.production-viewer-title{font-size:1.15rem;font-weight:650}
.production-player{width:min(100%,520px);display:grid;gap:8px;justify-items:center}
.production-wave{display:flex;align-items:center;justify-content:center;gap:4px;width:min(100%,460px);height:110px}
.production-wave i{flex:1 1 0;max-width:6px;min-width:2px;border-radius:3px;background:color-mix(in srgb,var(--ms-accent) 65%,transparent)}
.production-frame{width:min(60%,300px);aspect-ratio:16/9;border:1.5px dashed color-mix(in srgb,var(--ms-accent) 55%,var(--ms-line));border-radius:12px;background:linear-gradient(135deg,color-mix(in srgb,var(--ms-accent) 14%,transparent),transparent)}
.production-statusline{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin-top:12px}
.production-take-state{font-weight:650;color:var(--ms-muted);padding-left:12px;border-left:1px solid var(--ms-line)}
.production-take-state[data-on=true]{color:var(--ms-accent)}
.production-takes-head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:10px;margin:22px 0 12px;padding-top:18px;border-top:1px solid var(--ms-line)}
.production-takes-head .ms-section-title{margin:0!important;font-size:.85rem}
.production-takes{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,170px),1fr));gap:12px}
.production-body .production-take{appearance:none;display:flex;flex-direction:column;gap:8px;padding:8px 8px 10px;border:1px solid var(--ms-line);border-radius:12px;background:var(--ms-surface);color:inherit;text-align:left;min-width:0}
.production-take:hover:not(:disabled){border-color:color-mix(in srgb,var(--ms-accent) 40%,var(--ms-line))}
.production-take[aria-pressed=true]{border-color:var(--ms-accent);box-shadow:0 0 0 1px var(--ms-accent)}
.production-take-thumb{display:flex;align-items:center;justify-content:center;height:72px;border-radius:8px;background:var(--ms-raised);padding:0 12px;overflow:hidden}
.production-take-thumb .production-wave{height:44px;gap:2px}.production-take-thumb .production-wave i{background:color-mix(in srgb,var(--ms-text) 30%,transparent)}
.production-take[data-selected=true] .production-take-thumb .production-wave i{background:color-mix(in srgb,var(--ms-accent) 75%,transparent)}
.production-take-name{font-weight:650;padding:0 4px}.production-take[data-selected=true] .production-take-name{color:var(--ms-accent)}
.production-take .ms-meta{margin:0;padding:0 4px}

.production-create{min-width:0;border:1px solid var(--ms-line);border-radius:16px;background:var(--ms-surface);padding:20px}
.production-create h2{font-size:1.35rem;margin-bottom:12px}
.production-kinds{display:flex;flex-wrap:wrap;justify-content:space-between;gap:2px 2px;border-bottom:1px solid var(--ms-line);margin-bottom:4px}
.production-body .production-kind{appearance:none;border:0;border-bottom:2px solid transparent;border-radius:0;background:transparent;color:var(--ms-muted);font-size:12.5px;font-weight:600;padding:8px 3px;margin-bottom:-1px;white-space:nowrap}
.production-kind:hover:not(:disabled){color:var(--ms-text)}.production-kind:disabled{opacity:.45}
.production-kind[aria-pressed=true]{color:var(--ms-text);border-bottom-color:var(--ms-accent)}
.production-create-body{display:flex;flex-direction:column}
.production-create textarea{min-height:110px;margin-bottom:14px}
.production-label{display:block;font-weight:650;font-size:13px;margin-bottom:6px}
.production-refs{margin-bottom:16px}.production-refining{margin:0 0 12px!important}.production-kind-note{margin:0 0 12px!important;color:var(--ms-muted)}
.production-create .ms-method{padding:0 0 12px;border-top:0}.production-chip-add{border-style:dashed}
.production-create .pd-wide+.pd-wide{margin-top:8px}
.production-create .ms-notice{margin:0 0 12px!important;font-size:12.5px}
.production-import{display:flex;flex-direction:column}.production-import .production-row{margin-top:10px}

.production-comparison{border:1px solid var(--ms-line);border-radius:16px;background:var(--ms-surface);padding:20px;display:grid;gap:10px}
.production-comparison h3{font-size:1.15rem}.production-comparison h4{margin:0 0 4px;font-size:.95rem}
.production-comparison p{overflow-wrap:anywhere;color:var(--ms-muted);font-size:13px}
.production-comparison-slots{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.production-comparison-slot{min-width:0;border:1px solid var(--ms-line);padding:14px;border-radius:12px;display:grid;gap:8px;align-content:start;background:var(--ms-bg)}
.production-comparison-slot label{margin:0}
.production-comparison-active{border-color:var(--ms-accent);box-shadow:0 0 0 1px var(--ms-accent)}
.production-comparison button{min-height:36px;padding:6px 14px;border-radius:8px;border:1px solid var(--ms-line);background:var(--ms-surface);color:var(--ms-text);font-size:13px;font-weight:600}
.production-comparison button:hover:not(:disabled){background:var(--ms-raised)}
.production-comparison button:disabled{opacity:.5}.production-comparison button[aria-pressed=true]{background:color-mix(in srgb,var(--ms-accent) 18%,transparent);border-color:var(--ms-accent)}
.production-comparison-player{padding:12px;border:1px solid var(--ms-line);border-radius:10px;color:var(--ms-muted);font-size:13px}
.production-comparison-player:focus-visible{outline:2px solid var(--ms-accent);outline-offset:2px}
.production-comparison summary{cursor:pointer;min-height:28px;padding:4px 0;overflow-wrap:anywhere;color:var(--ms-faint);font-size:12.5px;font-weight:600}
.production-comparison input[type=range]{accent-color:var(--ms-accent)}

@container production (max-width:1060px){
.production-layout{grid-template-columns:minmax(0,1fr) minmax(250px,300px);gap:20px}
.production-left{display:contents}
.production-sections{grid-column:1/-1;flex-direction:row;flex-wrap:wrap;gap:6px;padding-bottom:12px}
.production-sections button{flex:1 1 auto;text-align:center;min-height:40px;border-color:var(--ms-line)}
.production-rail-plan{grid-column:1/-1;order:3}
.production-board{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,220px),1fr));align-items:start}
.production-layout[data-project=false]{grid-template-columns:minmax(0,1fr)}
}
@container production (max-width:700px){
.production-layout{grid-template-columns:minmax(0,1fr)}
.production-main{order:1}.production-create{order:2}
.production-title{font-size:1.35rem}.production-viewer{padding:18px}
.production-comparison-slots,.production-add-row{grid-template-columns:minmax(0,1fr)}
.production-create,.production-comparison{padding:16px}
}
@media(prefers-reduced-motion:reduce){.production-body *{animation:none!important;transition:none!important}}
`;

// studio/native/frontend/production-export.js
import { createElement as h7, useEffect as useEffect5, useRef as useRef5, useState as useState4 } from "react";
import { Button as Button3 } from "@hermes/plugin-sdk";

// studio/native/frontend/production-export-controller.js
var limit = 16777216;
var safeCodes = /* @__PURE__ */ new Set([
  "EXPORT_CANCELLED",
  "EXPORT_CLOSED",
  "EXPORT_SIZE_UNSUPPORTED",
  "EXPORT_FORMAT_UNSUPPORTED",
  "EXPORT_SELECTION_STALE",
  "EXPORT_SELECTED_TAKE_MISSING",
  "EXPORT_REVISION_CONFLICT",
  "EXPORT_SCOPE_CHANGED",
  "EXPORT_INTEGRITY_FAILED",
  "EXPORT_LINEAGE_INVALID",
  "EXPORT_IMPORT_UNAVAILABLE",
  "MEDIA_SCOPE_DENIED",
  "CREATION_INTEGRITY_FAILED",
  "RETAINED_SCOPE_CHANGED"
]);
var fileTypes = { "audio/wav": "wav", "image/png": "png", "image/jpeg": "jpeg", "video/mp4": "mp4" };
var ProductionExportController = class {
  // hooks.prepare(spec, valid) -> {descriptor,client,operation,identity,
  //   reauthorize():Promise<void>,release():Promise<void>}.
  // hooks.chooseDestination({filename,mime,size},valid) -> null (cancel), or
  //   {write(bytes,valid):Promise<{status:'saved'|'cancelled'|'unknown'}>,close?()}.
  // The trusted host adapter MUST check valid immediately before its file write.
  constructor(owner, hooks, notify = () => {
  }) {
    this.owner = owner;
    this.hooks = hooks;
    this.notify = notify;
    this.serial = 0;
    this.disposed = false;
    this.active = false;
    this.state = { busy: false, status: "Export selected retained outputs. No generation or conversion.", phase: "idle" };
  }
  emit(values) {
    if (!this.disposed) {
      Object.assign(this.state, values);
      this.notify({ ...this.state });
    }
  }
  cancel() {
    this.serial++;
    this.emit({ busy: this.active, phase: this.writing ? "unknown" : "cancelled", status: this.writing ? "Save File was already dispatched. Destination outcome is unverified; cancellation cannot undo it." : "Export cancelled before any further write. Nothing further will be dispatched." });
  }
  async save(assetIds, mode = "zip") {
    if (this.disposed || this.active) return;
    const owner = this.owner, current = owner.state.current, client = owner.client, epoch = owner.epoch;
    if (!current || !owner.valid(epoch, client) || owner.state.busy) return;
    if (typeof this.hooks?.prepare !== "function" || typeof this.hooks?.chooseDestination !== "function") {
      this.emit({ status: "Host Save File / export transport is unavailable. Nothing written.", phase: "unsupported" });
      return;
    }
    const ids = [...assetIds], serial = ++this.serial, production = current.id, revision = current.revision;
    const selectedAsset = owner.state.selectedAsset, selectedTake = owner.state.selectedTake;
    const pointers = ids.map((id) => ({ id, take: current.assets.find((item) => item.id === id)?.selected_take }));
    const valid = () => !this.disposed && serial === this.serial && owner.valid(epoch, client) && owner.state.current?.id === production && owner.state.current?.revision === revision && owner.state.selectedAsset === selectedAsset && owner.state.selectedTake === selectedTake && pointers.every((pin) => {
      const asset = owner.state.current.assets.find((item) => item.id === pin.id);
      return asset?.selected_take === pin.take && !asset?.stale;
    });
    let handle = null, destination = null, writing = false;
    this.active = true;
    this.emit({ busy: true, phase: "checking", status: "Checking exact selected retained bytes and saved revision..." });
    try {
      if (!ids.length || new Set(ids).size !== ids.length || !["zip", "file"].includes(mode) || mode === "file" && ids.length !== 1) throw Error("EXPORT_SELECTION_STALE");
      for (const id of ids) {
        const asset = current.assets.find((item) => item.id === id);
        if (!asset?.selected_take || asset.stale) throw Error("EXPORT_SELECTION_STALE");
      }
      handle = await this.hooks.prepare({ production, expected: revision, assets: ids, mode }, valid);
      if (!valid()) return;
      const descriptor = { ...handle.descriptor };
      if (!Number.isInteger(descriptor.size) || descriptor.size < 1 || descriptor.size > limit) throw Error("EXPORT_SIZE_UNSUPPORTED");
      if (mode === "zip" && (descriptor.mime !== "application/zip" || descriptor.filename !== "motion-studio-selected.zip") || mode === "file" && (!fileTypes[descriptor.mime] || !new RegExp("^\\d{2}-[a-z-]+-take-\\d{2}\\." + fileTypes[descriptor.mime] + "$").test(descriptor.filename))) throw Error("EXPORT_FORMAT_UNSUPPORTED");
      const identity = { ...handle.identity() };
      if (identity.take !== descriptor.take) throw Error("EXPORT_INTEGRITY_FAILED");
      const result = await readRetained(handle.client, handle.operation, () => identity, valid);
      if (!valid()) return;
      if (result.sha256 !== descriptor.sha256 || result.bytes.length !== descriptor.size) throw Error("EXPORT_INTEGRITY_FAILED");
      this.emit({ phase: "destination", status: "Verified bytes ready. Choose Save File or cancel; delivery is not yet verified." });
      destination = await this.hooks.chooseDestination({ filename: descriptor.filename, mime: descriptor.mime, size: descriptor.size }, valid);
      if (!valid()) return;
      if (!destination) {
        this.emit({ phase: "cancelled", status: "Save File cancelled. Nothing written." });
        return;
      }
      await handle.reauthorize();
      if (!valid()) return;
      writing = true;
      this.writing = true;
      const receipt = await destination.write(result.bytes, valid);
      if (!valid()) {
        if (!this.disposed && serial === this.serial) this.emit({ phase: "unknown", status: "Scope changed during Save File. Destination outcome is unverified; no retry." });
        return;
      }
      if (receipt?.status === "cancelled") this.emit({ phase: "cancelled", status: "Save File cancelled. Nothing written." });
      else if (receipt?.status === "ready") this.emit({ phase: "ready", status: "Download ready. Use the download link to save the verified original files." });
      else if (receipt?.status === "saved") this.emit({ phase: "saved", status: "Host reports file saved. Destination open/import/playback remains unverified." });
      else this.emit({ phase: "unknown", status: "Save File outcome unverified. Inspect the destination; no automatic retry." });
    } catch (error) {
      if (!this.disposed && serial === this.serial) {
        const code2 = safeCodes.has(error.code) ? error.code : safeCodes.has(error.message) ? error.message : null;
        this.emit({ phase: writing ? "unknown" : "blocked", status: writing ? "Save File outcome unverified. Inspect the destination; no automatic retry." : code2 ? /SCOPE/.test(code2) ? "The selected chat changed. Reopen the project before exporting." : /INTEGRITY/.test(code2) ? "The original bytes could not be verified. Reopen selected outputs." : "These outputs cannot be exported yet. Refresh and review their selections." : "Export unavailable. No destination write dispatched; reopen selected outputs." });
      }
    } finally {
      this.writing = false;
      try {
        await destination?.close?.();
      } catch {
      }
      try {
        await handle?.release?.();
      } catch {
      }
      this.active = false;
      if (!this.disposed) {
        if (serial === this.serial && !valid() && this.state.phase !== "unknown") this.emit({ phase: "blocked", status: "Export scope or selection changed. No further work dispatched." });
        this.emit({ busy: false });
      }
    }
  }
  dispose() {
    this.serial++;
    this.disposed = true;
  }
};

// studio/native/frontend/production-export.js
function ProductionExport({ owner, productionState, hooks }) {
  const controller = useRef5(null), [state, setState] = useState4(null), [choice, setChoice] = useState4({ key: "", ids: [] });
  const current = productionState?.current;
  const key = (productionState?.scopeEpoch ?? "") + ":" + (current?.id || "") + ":" + (current?.revision || "");
  const previousKey = useRef5(key);
  useEffect5(() => {
    const value = new ProductionExportController(owner, hooks, setState);
    controller.current = value;
    setState({ ...value.state });
    return () => {
      value.dispose();
      controller.current = null;
    };
  }, [owner, hooks]);
  useEffect5(() => {
    if (previousKey.current !== key) {
      previousKey.current = key;
      controller.current?.cancel();
    }
  }, [key]);
  const assets = current?.assets || [], selected = choice.key === key ? choice.ids : assets.filter((asset) => asset.selected_take && !asset.stale).map((asset) => asset.id);
  const busy = Boolean(state?.busy), unsupported = !hooks?.prepare || !hooks?.chooseDestination;
  const toggle = (id) => {
    controller.current?.cancel();
    owner.clearDownload?.();
    setChoice({ key, ids: selected.includes(id) ? selected.filter((value) => value !== id) : [...selected, id] });
  };
  const takeLabel = (asset) => {
    const index = (asset.takes || []).findIndex((take) => take.id === asset.selected_take);
    return !asset.selected_take ? "no take chosen" : asset.stale ? "out of date" : index < 0 ? "take chosen" : "Take " + (index + 1);
  };
  return h7(
    "section",
    { className: "production-export", "aria-label": "Export selected Production outputs" },
    h7("h3", null, "Export"),
    h7("p", { className: "production-muted" }, "Saves the original file of each chosen take (WAV, PNG, JPEG or MP4). The ZIP also holds a short list of what is inside. Up to 16 MB in total."),
    h7(
      "fieldset",
      { disabled: busy || !current || productionState?.busy },
      h7("legend", null, "Assets to export"),
      ...assets.map((asset) => h7("label", { key: asset.id }, h7("input", {
        type: "checkbox",
        checked: selected.includes(asset.id),
        disabled: !asset.selected_take || asset.stale,
        onChange: () => toggle(asset.id)
      }), asset.position + 1 + ". " + asset.kind + (asset.intent ? " - " + asset.intent : "") + " (" + takeLabel(asset) + ")"))
    ),
    h7(
      "div",
      { className: "production-row" },
      h7(Button3, {
        className: "ms-btn pd-btn pd-primary",
        disabled: busy || !selected.length || unsupported || productionState?.busy,
        onClick: () => controller.current?.save(selected, "zip")
      }, "Export assets"),
      h7(Button3, {
        className: "ms-btn pd-btn",
        variant: "outline",
        disabled: busy || selected.length !== 1 || unsupported || productionState?.busy,
        onClick: () => controller.current?.save(selected, "file")
      }, "Save selected file"),
      h7(Button3, { className: "ms-btn pd-btn", variant: "outline", disabled: !busy, onClick: () => {
        controller.current?.cancel();
        owner.clearDownload?.();
      } }, "Cancel export")
    ),
    h7("p", { className: "ms-help" }, !selected.length ? "Nothing to export yet: open Review, pick a take for an asset and choose Use take." : "Export assets saves one ZIP of everything ticked. Save selected file saves a single original when exactly one is ticked."),
    productionState?.download ? h7(
      "a",
      { className: "ms-link", href: productionState.download.url, download: productionState.download.filename },
      "Download " + productionState.download.filename
    ) : null,
    h7("p", { role: "status", "aria-live": "polite", className: "production-muted" }, unsupported ? "Saving files is not available in this window. Nothing was written." : state?.status)
  );
}

// studio/native/frontend/production-review.js
import { createElement as h10, useEffect as useEffect8, useRef as useRef8, useMemo, useState as useState7 } from "react";
import { Button as Button6 } from "@hermes/plugin-sdk";

// studio/native/frontend/media-review.js
import { createElement as h8, useCallback, useEffect as useEffect6, useRef as useRef6, useState as useState5 } from "react";
import { Button as Button4 } from "@hermes/plugin-sdk";

// studio/native/frontend/media-review-controller.js
var kinds = /* @__PURE__ */ new Set(["Image", "Video", "Voice", "Music", "Sound effects"]);
var formats = {
  Image: ["image/png", "image/jpeg", "image/webp", "image/gif", "image/avif", "image/bmp"],
  Video: ["video/mp4", "video/webm", "video/ogg"],
  audio: ["audio/wav", "audio/x-wav", "audio/wave", "audio/mpeg", "audio/mp4", "audio/ogg", "audio/webm", "audio/flac"]
};
var importMimes = { png: "image/png", jpeg: "image/jpeg", wav: "audio/wav", mp4: "video/mp4" };
var identityKeys = ["production", "asset", "request", "requestRevision", "take", "artifact"];
var sameIdentity = (a, b) => Boolean(a && b && identityKeys.every((key) => a[key] === b[key]));
var positive = (value) => Number.isFinite(value) && value > 0 ? value : null;
var emptyState = () => ({ slots: { A: null, B: null }, active: null, position: "0", volume: 1, status: "Choose an exact retained take. Nothing played." });
function normalizeMediaDescriptor(value) {
  if (!value || !kinds.has(value.kind) || !value.identity) throw Error("MEDIA_DESCRIPTOR_INVALID");
  const identity = {};
  for (const key of identityKeys) {
    const field = value.identity[key];
    if (key === "requestRevision") {
      if (field !== null && (!Number.isSafeInteger(field) || field < 1)) throw Error("MEDIA_DESCRIPTOR_INVALID");
    } else if ((key === "production" || key === "asset") && field === null) {
    } else if (typeof field !== "string" || !field.trim()) throw Error("MEDIA_DESCRIPTOR_INVALID");
    identity[key] = field;
  }
  if (typeof value.mime !== "string" || !Number.isSafeInteger(value.byteLength) || value.byteLength < 1 || value.byteLength > 16777216 || typeof value.reviewStatus !== "string" || !value.reviewStatus.trim()) throw Error("MEDIA_DESCRIPTOR_INVALID");
  if (value.format != null && (importMimes[value.format] !== value.mime || (value.format === "wav" ? !["Voice", "Music", "Sound effects"].includes(value.kind) : value.kind !== (value.format === "mp4" ? "Video" : "Image")))) throw Error("MEDIA_DESCRIPTOR_INVALID");
  if (value.sha256 != null && !/^[a-f0-9]{64}$/.test(value.sha256)) throw Error("MEDIA_DESCRIPTOR_INVALID");
  return Object.freeze({
    identity: Object.freeze(identity),
    kind: value.kind,
    format: value.format ?? null,
    mime: value.mime,
    byteLength: value.byteLength,
    width: positive(value.width),
    height: positive(value.height),
    duration: positive(value.duration),
    reviewStatus: value.reviewStatus,
    qualityRole: typeof value.qualityRole === "string" ? value.qualityRole : "Not recorded",
    sha256: value.sha256 ?? null
  });
}
function createRetainedReviewReader({ client, operation, valid, imported = false }) {
  return async ({ scope, descriptor, signal }) => {
    const current = () => !signal.aborted && valid(scope, descriptor.identity);
    if (!current()) throw Error("MEDIA_SCOPE_CHANGED");
    const id = descriptor.identity;
    if (!imported && (!id.production || !id.asset)) throw Error("MEDIA_DESCRIPTOR_INVALID");
    const transport = { request: async (name, payload) => {
      if (!current()) throw Error("MEDIA_SCOPE_CHANGED");
      const chunk = await client.request(name, payload);
      if (!current()) throw Error("MEDIA_SCOPE_CHANGED");
      if (imported && chunk.mime !== descriptor.mime) throw Error("MEDIA_ORIGINAL_UNAVAILABLE");
      return chunk;
    } };
    const result = await readRetained(transport, operation, () => imported ? { take: id.take } : { production: id.production, asset: id.asset, request: id.request, take: id.take }, current);
    if (!current() || !descriptor.sha256 || result.sha256 !== descriptor.sha256 || result.bytes.byteLength !== descriptor.byteLength)
      throw Error("MEDIA_ORIGINAL_UNAVAILABLE");
    return { scope, identity: id, bytes: result.bytes };
  };
}
function createImportedReviewReader(options) {
  return createRetainedReviewReader({ ...options, imported: true });
}
function createPlaybackGroup() {
  let active = null;
  return {
    claim(owner) {
      if (active !== owner) active?.pause();
      active = owner;
    },
    release(owner) {
      if (active === owner) active = null;
    }
  };
}
var mediaReviewPlaybackGroup = createPlaybackGroup();
var MediaReviewController = class {
  constructor({
    scope,
    readBytes,
    onChange = () => {
    },
    isScopeCurrent = () => true,
    playbackGroup = mediaReviewPlaybackGroup,
    urlAPI = URL,
    BlobClass = Blob
  }) {
    if (typeof scope !== "string" || !scope || typeof readBytes !== "function") throw Error("MEDIA_REVIEW_INPUT_INVALID");
    Object.assign(this, { scope, readBytes, onChange, isScopeCurrent, playbackGroup, urlAPI, BlobClass });
    this.state = emptyState();
    this.closed = false;
    this.player = null;
    this.playEpoch = 0;
  }
  current() {
    if (this.closed) return false;
    if (!this.isScopeCurrent(this.scope)) {
      this.dispose();
      return false;
    }
    return true;
  }
  emit() {
    if (!this.closed) this.onChange({ ...this.state, slots: { ...this.state.slots } });
  }
  supported(descriptor) {
    return (formats[descriptor.kind] || formats.audio).includes(descriptor.mime);
  }
  choose(slot, value) {
    if (!this.current() || !["A", "B"].includes(slot)) return;
    const descriptor = value ? normalizeMediaDescriptor(value) : null;
    const other = this.state.slots[slot === "A" ? "B" : "A"];
    if (descriptor && sameIdentity(descriptor.identity, other?.descriptor.identity)) {
      this.state.status = "Choose two distinct retained alternatives.";
      this.emit();
      return;
    }
    this.pause();
    this.releaseSlot(slot);
    if (descriptor) this.state.slots[slot] = { descriptor, url: null, loading: false, abort: null, decodedDuration: null, error: null };
    this.state.status = "Take context changed. Nothing played.";
    this.emit();
  }
  releaseSlot(slot) {
    const item = this.state.slots[slot];
    if (!item) return;
    item.abort?.abort();
    if (this.state.active === slot) {
      this.detach();
      this.state.active = null;
    }
    if (item.url) this.urlAPI.revokeObjectURL(item.url);
    this.state.slots[slot] = null;
  }
  async load(slot) {
    if (!this.current()) return;
    const item = this.state.slots[slot];
    if (!item || item.loading || item.url) return;
    if (!this.supported(item.descriptor)) {
      item.error = "Unsupported media format in this viewer. Original is unchanged.";
      this.emit();
      return;
    }
    item.abort = new AbortController();
    item.loading = true;
    item.error = null;
    this.emit();
    const valid = () => this.current() && this.state.slots[slot] === item && !item.abort.signal.aborted;
    try {
      if (!valid()) return;
      const result = await this.readBytes({
        scope: this.scope,
        descriptor: item.descriptor,
        identity: item.descriptor.identity,
        signal: item.abort.signal,
        valid
      });
      if (!valid()) return;
      if (result?.scope !== this.scope || !sameIdentity(result.identity, item.descriptor.identity) || !(result.bytes instanceof Uint8Array) || result.bytes.byteLength !== item.descriptor.byteLength) throw Error("MEDIA_ORIGINAL_UNAVAILABLE");
      const bytes2 = new Uint8Array(result.bytes);
      if (item.descriptor.sha256) {
        const digest2 = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes2)), (n) => n.toString(16).padStart(2, "0")).join("");
        if (!valid()) return;
        if (digest2 !== item.descriptor.sha256) throw Error("MEDIA_ORIGINAL_UNAVAILABLE");
      }
      if (!valid()) return;
      item.url = this.urlAPI.createObjectURL(new this.BlobClass([bytes2], { type: item.descriptor.mime }));
      item.loading = false;
      this.state.status = "Original bytes loaded. Playback and review approval have not started.";
      this.emit();
    } catch {
      if (!valid()) return;
      item.loading = false;
      item.error = "Original unavailable or integrity check failed. Retry explicitly; no work was started.";
      this.emit();
    }
  }
  attach(player) {
    if (this.player === player) return;
    this.detach();
    this.player = player;
    if (this.current()) this.syncPlayer();
  }
  detach() {
    this.pause();
    if (this.player) {
      this.player.removeAttribute("src");
      this.player.load();
    }
    this.player = null;
  }
  activate(slot) {
    if (!this.current()) return;
    const item = this.state.slots[slot];
    if (!item?.url || item.descriptor.kind === "Image" || item.error) return;
    this.pause();
    this.state.active = slot;
    this.state.status = "Monitor " + slot + " paused. Press Play deliberately.";
    this.syncPlayer();
    this.emit();
  }
  syncPlayer() {
    const item = this.state.slots[this.state.active];
    if (!this.player || !item?.url || item.error) return;
    if (this.player.tagName && this.player.tagName !== (item.descriptor.kind === "Video" ? "VIDEO" : "AUDIO")) return;
    this.player.autoplay = false;
    this.player.loop = false;
    this.player.volume = this.state.volume;
    this.player.src = item.url;
    this.player.load();
  }
  metadata(expectedURL) {
    if (!this.current()) return;
    const item = this.state.slots[this.state.active];
    if (!item || !this.player) return;
    if (expectedURL && item.url !== expectedURL) return;
    item.decodedDuration = positive(this.player.duration);
    this.applyPosition();
    this.emit();
  }
  applyPosition() {
    const value = this.state.position.trim() === "" ? NaN : Number(this.state.position);
    const duration = this.state.slots[this.state.active]?.decodedDuration;
    if (!Number.isFinite(value) || value < 0) {
      this.state.status = "Enter a finite position at or after zero.";
      return false;
    }
    if (!duration) {
      this.state.status = "Duration not decoded; playback unavailable until metadata is ready.";
      return false;
    }
    if (value >= duration) {
      this.state.status = "Position is at or beyond the end of this original. No retiming or automatic clamp.";
      return false;
    }
    try {
      this.player.currentTime = value;
    } catch {
      this.state.status = "This original cannot seek to that position.";
      return false;
    }
    return true;
  }
  seek(value) {
    if (!this.current()) return;
    this.pause();
    this.state.position = String(value);
    this.applyPosition();
    this.emit();
  }
  volume(value) {
    if (!this.current() || !Number.isFinite(Number(value))) return;
    this.state.volume = Math.max(0, Math.min(1, Number(value)));
    if (this.player) this.player.volume = this.state.volume;
    this.emit();
  }
  async play() {
    if (!this.current() || !this.player || !this.state.slots[this.state.active]?.url) return;
    const player = this.player, slot = this.state.active;
    if (this.state.slots[slot].error || !this.applyPosition()) {
      this.emit();
      return;
    }
    this.playbackGroup.claim(this);
    const epoch = ++this.playEpoch;
    try {
      await player.play();
      if (!this.current() || epoch !== this.playEpoch || player !== this.player || slot !== this.state.active) {
        player.pause();
        return;
      }
      this.state.status = "Playing original " + slot + ". Review status is unchanged.";
      this.emit();
    } catch {
      if (!this.current() || epoch !== this.playEpoch) return;
      player.pause();
      this.state.status = "Playback unavailable or blocked. Original is unchanged; press Play to retry.";
      this.emit();
    }
  }
  pause() {
    this.playEpoch++;
    this.player?.pause();
    this.playbackGroup.release(this);
    if (!this.closed) {
      this.state.status = "Paused. Nothing else started.";
      this.emit();
    }
  }
  position() {
    if (!this.current() || !this.player || this.player.paused) return;
    this.state.position = String(this.player.currentTime);
    this.emit();
  }
  ended() {
    this.pause();
    if (this.current()) {
      this.state.status = "Original ended. Other take did not start.";
      this.emit();
    }
  }
  mediaError(slot = this.state.active, expectedURL) {
    if (!this.current() || !this.state.slots[slot]) return;
    const item = this.state.slots[slot];
    if (expectedURL && item.url !== expectedURL) return;
    if (slot === this.state.active) this.detach();
    if (item.url) this.urlAPI.revokeObjectURL(item.url);
    item.url = null;
    item.error = "Browser cannot decode this original format or codec. Original is unchanged.";
    this.emit();
  }
  dispose() {
    if (this.closed) return;
    this.closed = true;
    this.detach();
    for (const slot of ["A", "B"]) this.releaseSlot(slot);
    this.state = emptyState();
    this.state.closed = true;
    this.state.status = "Review closed; scoped media cleared.";
    this.onChange({ ...this.state });
  }
};

// studio/native/frontend/media-review-style.js
var mediaReviewStyles = `
.media-review{color:var(--ms-text,var(--ui-text-primary,#f2efe6));background:var(--ms-surface,transparent);padding:18px;border:1px solid var(--ms-line,var(--ui-stroke-secondary,#343b36));border-radius:16px;min-width:0;display:grid;gap:10px}
.media-review *{box-sizing:border-box}.media-review p,.media-review summary{overflow-wrap:anywhere;font-size:13px;color:var(--ms-muted,inherit)}
.media-review h3{font-size:1.15rem}.media-review h4{margin:0 0 4px;font-size:.95rem}
.media-review-slots{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;align-items:start}
.media-review-slot{min-width:0;border:1px solid var(--ms-line,#343b36);padding:14px;border-radius:12px;background:var(--ms-bg,transparent)}
.media-review label{display:flex;flex-direction:column;gap:6px;margin:10px 0;min-width:0}
.media-review input,.media-review select,.media-review button{font:inherit;max-width:100%;min-width:0;min-height:36px}
.media-review input:not([type=range]),.media-review select{color:inherit;background:var(--ms-bg,transparent);border:1px solid var(--ms-line,#64756a);border-radius:8px;padding:6px 10px}
.media-review input[type=range]{accent-color:var(--ms-accent,#9be7c4)}
.media-review button{color:inherit;background:var(--ms-surface,transparent);border:1px solid var(--ms-line,#64756a);border-radius:8px;padding:6px 14px;font-size:13px;font-weight:600;white-space:normal;overflow-wrap:anywhere;cursor:pointer}
.media-review button:hover:not(:disabled){background:var(--ms-raised,transparent)}
.media-review button:disabled{opacity:.5;cursor:default}.media-review button[aria-pressed=true]{background:color-mix(in srgb,var(--ms-accent,#9be7c4) 18%,transparent);border-color:var(--ms-accent,#9be7c4)}
.media-review summary{cursor:pointer;min-height:32px;padding:6px 0;font-weight:600}
.media-review :is(button,input,select,summary,[tabindex]):focus-visible{outline:2px solid var(--ms-accent,#9be7c4);outline-offset:2px}
.media-review-image-viewport{max-width:100%;max-height:70vh;overflow:auto;background:color-mix(in srgb,var(--ms-text,#fff) 3%,transparent);border:1px solid var(--ms-line,#64756a);border-radius:10px;padding:2px}
.media-review-image-viewport img{display:block;height:auto}.media-review-monitor{min-width:0;margin-top:8px}
.media-review-monitor [role=group]{border:1px solid var(--ms-line,#64756a);border-radius:10px;padding:12px}
.media-review video,.media-review audio{display:block;width:100%;max-width:100%;max-height:70vh;object-fit:contain;border-radius:8px}
.media-review-actions{display:flex;flex-wrap:wrap;gap:8px}
.media-review-one{padding:20px}.media-review-single{display:grid;gap:14px;justify-items:stretch}
.media-review-wait{min-height:160px;display:grid;place-content:center;justify-items:center;gap:10px;text-align:center}
.media-review-badges{display:flex;flex-wrap:wrap;gap:6px}.media-review-badge{display:inline-flex;padding:2px 8px;border-radius:6px;font-size:11.5px;font-weight:650;background:var(--ms-raised,rgba(128,128,128,.2));color:var(--ms-muted,inherit)}
.media-review-facts{display:grid;gap:4px}.media-review-facts summary{color:var(--ms-faint,inherit);font-size:12.5px}
.media-review label.media-review-zoom{flex-direction:row;align-items:center;gap:8px;margin:0 0 8px;font-size:13px}.media-review-zoom select{width:auto}
.media-review-slot[data-on=true]{border-color:var(--ms-accent,#9be7c4)}
.media-review-controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:0 16px}
@media(max-width:600px){.media-review-slots{grid-template-columns:minmax(0,1fr)}.media-review{padding:12px}.media-review-slot{padding:10px}}
@media(prefers-reduced-motion:reduce){.media-review *{animation:none!important;transition:none!important}}
`;

// studio/native/frontend/media-review.js
var initialState = { slots: { A: null, B: null }, active: null, position: "0", volume: 1, status: "" };
var takeName = (descriptor, index) => "Take " + (index + 1);
var seconds = (value) => value >= 60 ? Math.floor(value / 60) + " min " + Math.round(value % 60) + " s" : (value < 10 ? Math.round(value * 10) / 10 : Math.round(value)) + " s";
var bytes = (value) => value >= 1048576 ? (value / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(value / 1024)) + " KB";
var mediaName = (descriptor) => descriptor.kind + " take" + (descriptor.duration === null ? "" : ", " + seconds(descriptor.duration));
var PLAIN = [
  [/^Choose an exact retained take\..*|^Take context changed\..*/, ""],
  [/^Choose two distinct.*/, "Pick two different takes."],
  [/^Original bytes loaded\..*/, "Ready. Nothing plays until you press play."],
  [/^Monitor (A|B) paused\..*/, "Take $1 is ready. Press Play."],
  [/^Playing original (A|B)\..*/, "Playing take $1."],
  [/^Paused\..*/, "Paused."],
  [/^Original ended\..*/, "Finished."],
  [/^Review closed.*/, "Viewer closed."],
  [/^Position is at or beyond.*/, "That start time is past the end of this take."],
  [/^Duration not decoded.*/, "Still loading the file. Try again in a moment."],
  [/^Enter a finite position.*/, "Enter a start time of 0 or more."],
  [/^Playback unavailable.*/, "Could not play. Press Play to try again."],
  [/^This original cannot seek.*/, "This file cannot jump to that time."],
  [/^Unsupported media format.*/, "This viewer cannot show this file type. The file is unchanged."],
  [/^Original unavailable.*/, "Could not load the file. Try again."],
  [/^Browser cannot decode.*/, "This browser cannot play this file. The file is unchanged."]
];
var plain = (text) => {
  const value = String(text || ""), match = PLAIN.find(([pattern]) => pattern.test(value));
  return match ? value.replace(match[0], match[1]) : value;
};
var EXTENSIONS = { "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "image/png": "png", "image/jpeg": "jpeg", "video/mp4": "mp4" };
var badge2 = (text) => text ? h8("span", { className: "ms-badge media-review-badge" }, text) : null;
function ImageOriginal({ item, slot, controller }) {
  const [zoom, setZoom] = useState5("fit"), [dimensions, setDimensions] = useState5(null);
  const width = dimensions?.width ?? item.descriptor.width;
  return h8(
    "div",
    { className: "media-review-image" },
    h8("label", { className: "media-review-zoom" }, "Zoom", h8(
      "select",
      {
        "aria-label": "Image zoom " + slot,
        value: zoom,
        onChange: (event) => setZoom(event.target.value)
      },
      h8("option", { value: "fit" }, "Fit"),
      h8("option", { value: "100" }, "100%"),
      h8("option", { value: "200" }, "200%")
    )),
    h8(
      "div",
      {
        className: "media-review-image-viewport",
        tabIndex: 0,
        role: "region",
        "aria-label": "Image " + slot + " - arrow keys scroll when zoomed in"
      },
      h8("img", {
        src: item.url,
        alt: mediaName(item.descriptor),
        style: zoom === "fit" ? { width: "100%", maxHeight: "70vh", objectFit: "contain" } : { width: width ? width * Number(zoom) / 100 : void 0, maxWidth: "none" },
        onLoad: (event) => setDimensions({ width: event.target.naturalWidth, height: event.target.naturalHeight }),
        onError: () => controller.mediaError(slot, item.url)
      })
    ),
    dimensions ? h8("p", null, dimensions.width + " x " + dimensions.height + " pixels") : null
  );
}
function DescriptorFacts({ descriptor, slot }) {
  const id = descriptor.identity, size = descriptor.width && descriptor.height ? descriptor.width + " x " + descriptor.height : null;
  return h8(
    "div",
    { className: "media-review-facts" },
    h8(
      "div",
      { className: "media-review-badges" },
      badge2(descriptor.kind),
      descriptor.duration === null ? null : badge2(seconds(descriptor.duration)),
      badge2(size),
      badge2(bytes(descriptor.byteLength)),
      badge2(descriptor.reviewStatus)
    ),
    h8(
      "details",
      null,
      h8("summary", null, "Technical details" + (slot ? " " + slot : "")),
      h8("p", null, descriptor.mime + " / " + descriptor.byteLength + " bytes"),
      ...Object.entries(id).filter(([, value]) => value != null).map(([key, value]) => h8("p", { key }, key + ": " + value))
    )
  );
}
function MediaReview(props) {
  let descriptors;
  try {
    descriptors = props.descriptors.map(normalizeMediaDescriptor);
  } catch {
    return h8(
      "section",
      { "aria-label": "Media viewer" },
      h8("p", { role: "status" }, "This take cannot be shown here. Nothing was opened.")
    );
  }
  return h8(MediaReviewSession, { ...props, descriptors, key: JSON.stringify([props.scope, descriptors, Boolean(props.single)]) });
}
function SingleViewer({ state, session, playerRef }) {
  const item = state.slots.A, requested = useRef6(null);
  useEffect6(() => {
    if (!item || requested.current === item) return;
    requested.current = item;
    void session.current?.load("A");
  }, [item, session]);
  useEffect6(() => {
    if (item?.url && item.descriptor.kind !== "Image" && state.active !== "A") session.current?.activate("A");
  }, [item?.url, state.active, session]);
  if (!item) return h8("p", { className: "media-review-wait" }, "Opening the take...");
  const kind = item.descriptor.kind, ready = item.url && state.active === "A";
  return h8(
    "div",
    { className: "media-review-single" },
    item.loading || !item.url && !item.error ? h8("p", { className: "media-review-wait" }, "Loading the original file...") : null,
    item.error ? h8(
      "div",
      { className: "media-review-wait" },
      h8("p", { role: "status" }, plain(item.error)),
      h8(Button4, { className: "ms-btn", variant: "outline", onClick: () => void session.current?.load("A") }, "Try again")
    ) : null,
    item.url && kind === "Image" ? h8(ImageOriginal, { key: item.url, item, slot: "A", controller: session.current }) : null,
    ready ? h8(kind === "Video" ? "video" : "audio", {
      key: kind === "Video" ? "video" : "audio",
      ref: playerRef,
      controls: true,
      preload: "metadata",
      playsInline: true,
      "aria-label": mediaName(item.descriptor),
      onLoadedMetadata: () => session.current?.metadata(item.url),
      onPlay: () => session.current?.playbackGroup.claim(session.current),
      onEnded: () => session.current?.playbackGroup.release(session.current),
      onError: () => session.current?.mediaError("A", item.url)
    }) : null,
    item.url ? h8(
      "a",
      { className: "ms-link", href: item.url, download: "motion-studio-original." + (EXTENSIONS[item.descriptor.mime] || "bin") },
      "Save / download original " + (EXTENSIONS[item.descriptor.mime] || "file").toUpperCase()
    ) : null,
    h8(DescriptorFacts, { descriptor: item.descriptor, slot: "" })
  );
}
function MediaReviewSession({ scope, descriptors, readBytes, isScopeCurrent, onController, playbackGroup, single = false }) {
  const [state, setState] = useState5(initialState), session = useRef6(null);
  useEffect6(() => {
    const current = new MediaReviewController({ scope, readBytes, isScopeCurrent, playbackGroup, onChange: setState });
    session.current = current;
    setState({ ...initialState });
    onController?.(current);
    return () => {
      current.onChange = () => {
      };
      current.dispose();
      if (session.current === current) session.current = null;
      onController?.(null);
    };
  }, [scope, readBytes, isScopeCurrent, onController, playbackGroup]);
  const playerRef = useCallback((node) => session.current?.attach(node), []);
  const button = (label, action, disabled = false, extra = {}) => h8(Button4, { className: "ms-btn", variant: "outline", onClick: action, disabled, ...extra }, label);
  if (state.closed) return h8("section", { "aria-label": "Media viewer" }, h8("p", { role: "status" }, plain(state.status)));
  if (single) return h8(
    "section",
    { "aria-label": "Media viewer", className: "media-review media-review-one" },
    h8("style", null, mediaReviewStyles),
    h8(SingleViewer, { state, session, playerRef })
  );
  const active = state.slots[state.active], timeBased = active && active.descriptor.kind !== "Image";
  return h8(
    "section",
    { "aria-label": "Media viewer", className: "media-review" },
    h8("style", null, mediaReviewStyles),
    h8("h3", null, "Compare two takes"),
    h8("p", null, "Comparing only looks and listens. It does not choose a take or change any file."),
    h8("div", { className: "media-review-slots" }, ...["A", "B"].map((slot) => {
      const item = state.slots[slot], other = state.slots[slot === "A" ? "B" : "A"];
      const selected = item ? descriptors.findIndex((value) => value.identity.take === item.descriptor.identity.take && value.identity.artifact === item.descriptor.identity.artifact && value.identity.asset === item.descriptor.identity.asset) : -1;
      return h8(
        "article",
        { key: slot, className: "media-review-slot", "data-on": String(state.active === slot) },
        h8("h4", null, "Take " + slot + (state.active === slot ? " - now playing from" : "")),
        h8("label", null, "Take " + slot, h8(
          "select",
          {
            "aria-label": "Take " + slot,
            value: selected < 0 ? "" : String(selected),
            onChange: (event) => session.current?.choose(slot, event.target.value === "" ? null : descriptors[Number(event.target.value)])
          },
          h8("option", { value: "" }, "Choose a take"),
          ...descriptors.map((descriptor, index) => h8(
            "option",
            { key: index, value: String(index), disabled: JSON.stringify(descriptor.identity) === JSON.stringify(other?.descriptor.identity) },
            takeName(descriptor, index)
          ))
        )),
        item ? h8(
          "div",
          null,
          h8(DescriptorFacts, { descriptor: item.descriptor, slot }),
          item.url ? null : button(item.loading ? "Loading " + slot + "..." : "Load take " + slot, () => void session.current?.load(slot), item.loading),
          item.error ? h8("p", { role: "status" }, plain(item.error)) : null,
          item.url ? h8("div", null, item.descriptor.kind === "Image" ? h8(ImageOriginal, { key: item.url, item, slot, controller: session.current }) : button("Listen to " + slot, () => session.current?.activate(slot), false, { "aria-pressed": state.active === slot })) : null
        ) : null
      );
    })),
    timeBased ? h8(
      "div",
      { className: "media-review-monitor" },
      h8(
        "div",
        { tabIndex: 0, role: "group", "aria-label": "Player - press Space to play or pause", onKeyDown: (event) => {
          if (event.target === event.currentTarget && event.code === "Space") {
            event.preventDefault();
            if (session.current?.player?.paused) void session.current.play();
            else session.current?.pause();
          }
        } },
        h8(active.descriptor.kind === "Video" ? "video" : "audio", {
          key: active.descriptor.kind === "Video" ? "video" : "audio",
          ref: playerRef,
          preload: "metadata",
          playsInline: true,
          "aria-label": "Take " + state.active + ": " + mediaName(active.descriptor),
          onLoadedMetadata: () => session.current?.metadata(active.url),
          onTimeUpdate: () => session.current?.position(),
          onEnded: () => session.current?.ended(),
          onError: () => session.current?.mediaError(state.active, active.url)
        })
      ),
      h8(
        "div",
        { className: "media-review-controls" },
        h8("label", null, "Start at (seconds)", h8("input", {
          type: "number",
          min: 0,
          step: "any",
          "aria-label": "Start at seconds",
          value: state.position,
          onChange: (event) => session.current?.seek(event.target.value)
        })),
        h8("label", null, "Same volume for both", h8("input", {
          type: "range",
          min: 0,
          max: 1,
          step: 0.01,
          "aria-label": "Same volume for both",
          value: state.volume,
          onChange: (event) => session.current?.volume(event.target.value)
        }))
      ),
      h8(
        "div",
        { className: "media-review-actions" },
        button("Play " + state.active, () => void session.current?.play()),
        button("Play from start", () => {
          session.current?.seek("0");
          void session.current?.play();
        }),
        button("Pause", () => session.current?.pause())
      ),
      h8("p", null, "Both takes use the same start time and volume. Switching takes pauses playback; lengths and loudness are not matched.")
    ) : h8("p", null, "Choose a take on each side and load it to compare."),
    h8("p", { role: "status", "aria-label": "Viewer status" }, plain(state.status))
  );
}

// studio/native/frontend/production-comparison.js
import { createElement as h9, useEffect as useEffect7, useRef as useRef7, useState as useState6 } from "react";
import { Button as Button5 } from "@hermes/plugin-sdk";

// studio/native/frontend/production-controller.js
async function insertDraft2(host2, session, text) {
  const composer = host2?.composer;
  if (!composer?.insertText) return false;
  if (await composer.insertText(session, text, { mode: "block" })) return true;
  if (typeof host2.openSession !== "function") return false;
  try {
    await host2.openSession(session);
  } catch {
    return false;
  }
  for (let i = 0; i < 10; i++) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    if (await composer.insertText(session, text, { mode: "block" })) {
      try {
        composer.focus?.(session);
      } catch {
      }
      return true;
    }
  }
  return false;
}
var methods2 = /* @__PURE__ */ new Set([
  "list",
  "open",
  "admit",
  "create",
  "update_brief",
  "add_asset",
  "update_asset",
  "add_reference",
  "update_reference",
  "link_take",
  "select_take",
  "chunk",
  "describe",
  ...["intent", "begin", "chunk", "status", "commit", "cancel", "describe", "read_chunk"].map((name) => "media_import." + name),
  ...["prepare", "descriptor", "chunk", "close"].map((name) => "export." + name)
]);
var safeRejections = /* @__PURE__ */ new Set([
  "PRODUCTION_STALE_REVISION",
  "PRODUCTION_ASSET_NOT_FOUND",
  "PRODUCTION_REFERENCE_NOT_FOUND",
  "PRODUCTION_MEDIA_KIND_MISMATCH",
  "PRODUCTION_DEPENDENCY_INVALID",
  "PRODUCTION_DEPENDENCY_CYCLE",
  "PRODUCTION_TAKE_NOT_LINKED"
]);
var recoveryKey = "motion-studio.production.unresolved-create-v1";
var authorityDenials = /* @__PURE__ */ new Set([
  "PRODUCTION_ACCESS_UNAVAILABLE",
  "PRODUCTION_SCOPE_DENIED",
  "PRODUCTION_WORKFLOW_REVIEW_REQUIRED",
  "PRODUCTION_TAKE_SCOPE_MISMATCH",
  "CREATION_ACCESS_UNAVAILABLE",
  "CREATION_CONTEXT_REQUIRED",
  "CREATION_SCOPE_DENIED",
  "CREATION_WORKFLOW_REVIEW_REQUIRED",
  "CREATION_STORE_REVIEW_REQUIRED",
  "CREATION_RETIRED",
  "MUSIC_SCOPE_REVIEW_REQUIRED",
  "MUSIC_WORKFLOW_REVIEW_REQUIRED",
  "MUSIC_POLICY_CHANGED",
  "MUSIC_BINDING_DENIED",
  "MUSIC_EFFECT_REVIEW_REQUIRED"
]);
function productionMessage(code2, fallback = "This action is unavailable. Refresh the saved project and try again.") {
  code2 = code2 || fallback;
  const messages2 = {
    PRODUCTION_PRIMARY_UNAVAILABLE: "Open or select a Motion Studio chat in the sidebar, then come back here.",
    PRODUCTION_STALE_REVISION: "The project changed. Refresh before saving this edit.",
    PRODUCTION_OPERATION_UNAVAILABLE: "The reply could not be confirmed. Reopen the project before trying again.",
    CREATION_INTEGRITY_FAILED: "The original bytes could not be verified. Reopen the take and try again.",
    RETAINED_SCOPE_CHANGED: "The selected chat or take changed. Reopen the original."
  };
  if (messages2[code2]) return messages2[code2];
  if (authorityDenials.has(code2) || /SCOPE|ACCESS|PRIMARY|POLICY|BINDING/.test(code2 || "")) return "This chat cannot access that media. Reopen the matching profile and chat.";
  if (/REVISION|STALE/.test(code2 || "")) return "Saved inputs changed. Refresh and review the current selection.";
  return /^[A-Z][A-Z0-9_]+$/.test(fallback) ? "This action is unavailable. Reopen the matching chat and project." : fallback;
}
var command2 = () => crypto.randomUUID().replaceAll("-", "");
var draftOwners = /* @__PURE__ */ new WeakMap();
function draftsFor(host2) {
  if (draftOwners.has(host2)) return draftOwners.get(host2);
  const drafts = /* @__PURE__ */ new Map();
  draftOwners.set(host2, drafts);
  for (const key of ["focusedSessionId", "focusedSessionOwner", "connectionId", "profile", "gateway"]) {
    let prior = JSON.stringify(host2.state[key]?.get());
    host2.state[key]?.subscribe((value) => {
      const next = JSON.stringify(value);
      if (next !== prior) drafts.clear();
      prior = next;
    });
  }
  return drafts;
}
function records() {
  try {
    return JSON.parse(globalThis.localStorage?.getItem(recoveryKey) || "{}");
  } catch {
    return {};
  }
}
function stored(scope) {
  const value = records()[scope];
  return value?.operation === "create" && /^[a-f0-9]{32}$/.test(value.command) ? value : null;
}
function retain(scope, pending) {
  try {
    const all = records();
    all[scope] = { operation: "create", command: pending.command };
    globalThis.localStorage.setItem(recoveryKey, JSON.stringify(all));
    return stored(scope)?.command === pending.command;
  } catch {
    return false;
  }
}
function releaseStored(scope, pending) {
  try {
    const all = records();
    if (all[scope]?.command === pending?.command) {
      delete all[scope];
      if (Object.keys(all).length) globalThis.localStorage.setItem(recoveryKey, JSON.stringify(all));
      else globalThis.localStorage.removeItem(recoveryKey);
    }
  } catch {
  }
}
var ProductionController = class {
  constructor(host2, notify = () => {
  }) {
    this.host = host2;
    this.directionDrafts = draftsFor(host2);
    this.notify = notify;
    this.client = null;
    this.epoch = 0;
    this.disposed = false;
    this.url = null;
    this.pendingScope = this.scope();
    this.pending = this.restore();
    this.state = {
      productions: [],
      current: null,
      available: [],
      capabilities: {},
      selectedAsset: null,
      selectedTake: null,
      busy: false,
      pending: Boolean(this.pending),
      scopeEpoch: 0,
      methods: null,
      methodsLoading: false,
      methodsError: false,
      status: this.pending ? "Unresolved Create restored. Reconcile exactly; replacement Create is locked." : "Open a saved Production or create a brief. No work started.",
      url: null,
      urlTake: null
    };
  }
  scope() {
    return JSON.stringify({
      root: this.host.state.focusedSessionId?.get() || "",
      connection: this.host.state.connectionId?.get() || "",
      profile: this.host.state.profile?.get() || ""
    });
  }
  restore() {
    const value = stored(this.scope());
    return value ? { operation: "create", command: value.command, payload: null } : null;
  }
  bindRecovery() {
    const scope = this.scope(), restored = this.restore();
    if (scope !== this.pendingScope) this.pending = restored;
    else if (restored && restored.command !== this.pending?.command) this.pending = restored;
    this.pendingScope = scope;
  }
  release(pending) {
    if (this.pending === pending) this.pending = null;
    releaseStored(this.scope(), pending);
  }
  emit(values) {
    if (this.disposed) return;
    Object.assign(this.state, values, { scopeEpoch: this.epoch });
    this.notify({ ...this.state });
  }
  clear() {
    const cleanup = this.reviewCleanup;
    this.reviewCleanup = null;
    cleanup?.();
    this.loadSerial = (this.loadSerial || 0) + 1;
    this.clearDownload();
    this.emit({ mediaReview: null });
    if (this.loading) {
      this.loading = false;
      this.emit({ busy: false });
    }
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = null;
    this.emit({ url: null, urlTake: null, comparisonOpen: false });
  }
  compare() {
    const asset = this.state.current?.assets.find((item) => item.id === this.state.selectedAsset);
    if (!this.valid(this.epoch) || this.state.busy || this.state.comparisonOpen || asset?.kind !== "Sound effects" || asset.takes.length < 2) return;
    if (asset.takes.some((take) => take.origin === "user_import")) return this.prepareMediaReview();
    this.clear();
    this.emit({ comparisonOpen: true });
  }
  valid(epoch, client = this.client) {
    return !this.disposed && epoch === this.epoch && client?.current();
  }
  identityValid(identity) {
    return !identity || identity.epoch === this.epoch && identity.production === (this.state.current?.id || null) && (identity.asset === void 0 || identity.asset === this.state.selectedAsset) && (identity.revision === void 0 || identity.revision === this.state.current?.revision);
  }
  invalidate() {
    this.waitingForChat = !this.host.state?.focusedSessionId?.get();
    this.directionDrafts.clear();
    this.bindRecovery();
    this.epoch++;
    this.clear();
    this.emit({
      methods: null,
      methodsLoading: false,
      methodsError: false,
      productions: [],
      current: null,
      available: [],
      capabilities: {},
      selectedAsset: null,
      selectedTake: null,
      draftAsset: null,
      importRequests: [],
      importing: false,
      importProgress: null,
      busy: false,
      connecting: false,
      connectionStatus: null,
      needsConnection: !this.waitingForChat,
      pending: Boolean(this.pending),
      status: this.waitingForChat ? "Open or select a Motion Studio chat in the sidebar, then come back here." : "Selected chat/profile/connection changed. Reopen; no command replayed."
    });
  }
  resetForOpen() {
    this.importJob = null;
    this.emit({ connecting: false, connectionStatus: null, needsConnection: false, methods: null, methodsLoading: false, methodsError: false, importRequests: [], draftAsset: null, importing: false, importProgress: null });
    this.client?.dispose();
    this.epoch++;
    this.clear();
    this.emit({
      current: null,
      available: [],
      selectedAsset: null,
      selectedTake: null,
      busy: false,
      pending: Boolean(this.pending)
    });
  }
  failure(error, fallback) {
    if (authorityDenials.has(error.code)) {
      this.directionDrafts.clear();
      this.epoch++;
      this.client?.dispose();
      this.clear();
      this.emit({
        connectionStatus: null,
        methods: null,
        methodsLoading: false,
        methodsError: false,
        productions: [],
        current: null,
        available: [],
        capabilities: {},
        selectedAsset: null,
        selectedTake: null,
        importRequests: [],
        draftAsset: null,
        importing: false,
        importProgress: null
      });
      if (this.pending) this.pending = { ...this.pending, payload: null };
    }
    this.emit({ busy: false, pending: Boolean(this.pending), needsConnection: ["PRODUCTION_WORKFLOW_REVIEW_REQUIRED", "CREATION_WORKFLOW_REVIEW_REQUIRED"].includes(error.code), status: productionMessage(error.code, fallback) });
  }
  publish(result, status = "Saved Production observed. Nothing generated.") {
    const current = result.current, assets = current?.assets || [];
    const selectedAsset = assets.some((a) => a.id === this.state.selectedAsset) ? this.state.selectedAsset : assets[0]?.id || null;
    const asset = assets.find((a) => a.id === selectedAsset), takes = asset?.takes || [];
    const selectedTake = takes.some((t) => t.id === this.state.selectedTake) ? this.state.selectedTake : asset?.selected_take || takes[0]?.id || null;
    if (this.state.comparisonOpen || selectedAsset !== this.state.selectedAsset || selectedTake !== this.state.selectedTake || current?.revision !== this.state.current?.revision) this.clear();
    this.emit({
      current,
      productions: result.productions || this.state.productions,
      available: result.available || [],
      capabilities: result.capabilities || {},
      selectedAsset,
      selectedTake,
      busy: false,
      pending: Boolean(this.pending),
      status
    });
  }
  observePending(result, productions = []) {
    const pending = this.pending;
    if (!pending) return;
    const match = pending.operation === "create" && (result.current?.command === pending.command || productions.some((item) => item.command === pending.command));
    if (match) {
      this.release(pending);
      this.emit({ pending: false, status: "Lost Create reconciled from saved command. No duplicate dispatched." });
    } else this.emit({ pending: true, status: "Unresolved Create remains locked. An absent or failed list is not non-commit proof; reconcile again." });
  }
  watchFocusedChat() {
    if (this.stopFocusedChat) return;
    const focused = this.host.state?.focusedSessionId;
    if (!focused?.subscribe) return;
    let previous = focused.get(), serial = 0;
    this.stopFocusedChat = focused.subscribe((value) => {
      const changed = value !== previous;
      previous = value;
      if (changed) serial++;
      if (!value) this.waitingForChat = true;
      if (!changed || !value || !this.waitingForChat || this.disposed) return;
      const ticket = serial;
      queueMicrotask(() => {
        if (this.disposed || ticket !== serial || focused.get() !== value) return;
        this.waitingForChat = false;
        void this.open();
      });
    });
  }
  async open(production = null) {
    this.watchFocusedChat();
    this.waitingForChat = !this.host.state?.focusedSessionId?.get();
    this.resetForOpen();
    const epoch = this.epoch;
    this.emit({ busy: true });
    let client;
    try {
      client = await openTechnical(this.host, () => this.invalidate(), { namespace: "production", methods: methods2 });
      if (this.disposed || epoch !== this.epoch) {
        client.dispose();
        return;
      }
      this.client = client;
      this.bindRecovery();
      this.emit({ pending: Boolean(this.pending) });
      const listed = await client.request("list");
      if (!this.valid(epoch, client)) return;
      this.emit({ productions: listed.productions, available: listed.available, capabilities: listed.capabilities });
      const pendingId = this.pending?.operation === "create" ? listed.productions.find((item) => item.command === this.pending.command)?.id : null;
      if (this.pending?.operation === "create" && !pendingId) {
        this.publish({ ...listed, current: null }, "Unresolved Create remains locked. Retry exact observation; no replacement is allowed.");
        return;
      }
      const id = pendingId || production || listed.productions[0]?.id;
      const result = id ? await client.request("open", { production: id }) : listed;
      if (!this.valid(epoch, client)) return;
      this.publish({ ...result, productions: listed.productions }, "Saved Production reopened. No mutation or generation dispatched.");
      this.observePending({ ...result, productions: listed.productions }, listed.productions);
    } catch (error) {
      if (!this.disposed && epoch === this.epoch) this.failure(error, "PRODUCTION_ACCESS_UNAVAILABLE");
    }
  }
  async refresh() {
    const client = this.client, epoch = this.epoch, id = this.state.current?.id;
    if (!this.valid(epoch, client) || this.state.busy) return;
    this.emit({ busy: true });
    try {
      const result = await client.request(id ? "open" : "list", id ? { production: id } : {});
      if (!this.valid(epoch, client)) return;
      this.publish(result, "Saved state observed. No command replayed.");
      this.observePending(result, result.productions || []);
    } catch (error) {
      if (this.valid(epoch, client)) this.failure(error, "Reply unobserved. Reopen to reconcile; do not resubmit.");
    }
  }
  async admit() {
    if (this.disposed || this.state.busy || this.pending) return;
    this.resetForOpen();
    this.invalidate();
    const epoch = this.epoch;
    this.emit({ busy: true, connecting: true, connectionStatus: "Connecting\u2026", status: "Connecting\u2026" });
    try {
      const client = await openTechnical(this.host, () => this.invalidate(), { namespace: "production", methods: methods2 });
      if (this.disposed || epoch !== this.epoch) {
        client.dispose();
        return;
      }
      this.client = client;
      this.bindRecovery();
      if (this.pending) {
        this.emit({ busy: false, connecting: false, connectionStatus: "Check the interrupted save before connecting this chat." });
        return;
      }
      await client.request("admit");
      if (!this.valid(epoch, client)) return;
      const result = await client.request("list");
      if (!this.valid(epoch, client)) return;
      this.publish({ ...result, current: null }, "This chat is connected");
      this.emit({ connecting: false, needsConnection: false, connectionStatus: "This chat is connected" });
    } catch (error) {
      if (!this.disposed && epoch === this.epoch) {
        this.failure(error, "PRODUCTION_ACCESS_UNAVAILABLE");
        this.emit({ connecting: false, connectionStatus: error.code === "CREATION_WORKFLOW_REVIEW_REQUIRED" ? "Connect this chat in Quick Create first, then connect it to Production." : "Cannot connect this chat. Check the selected chat and its configured access, then try again." });
      }
    }
  }
  newBrief() {
    if (this.state.busy || this.pending) return;
    this.clear();
    this.emit({ draftAsset: null });
    this.emit({
      current: null,
      selectedAsset: null,
      selectedTake: null,
      status: "New Production brief. No saved head or command assumed."
    });
  }
  chooseAsset(asset) {
    if (this.state.busy) return;
    this.clear();
    this.emit({ selectedAsset: asset, selectedTake: this.state.current?.assets.find((a) => a.id === asset)?.selected_take || null });
  }
  chooseTake(take) {
    if (this.state.busy) return;
    this.clear();
    this.emit({ selectedTake: take });
  }
  async mutate(operation, payload = {}, identity = null) {
    const client = this.client, epoch = this.epoch, current = this.state.current;
    if (!this.identityValid(identity)) {
      this.emit({ status: "Stale visual scope rejected. Reopen and review current saved state." });
      return;
    }
    if (operation === "create") this.bindRecovery();
    if (this.pending) {
      this.emit({ pending: true, status: "Uncertain command locked. Reconcile it before any replacement mutation." });
      return;
    }
    if (!this.valid(epoch, client) || this.state.busy) return;
    const revisioned = operation !== "create";
    if (revisioned && !current) return;
    const full = { ...payload, command: command2(), ...revisioned ? { production: current.id, expected: payload.expected ?? current.revision } : {} };
    const pending = { operation, command: full.command, payload: full };
    if (operation === "create" && !retain(this.scope(), pending)) {
      this.emit({ busy: false, pending: false, status: "Durable Create recovery marker unavailable. No command dispatched." });
      return;
    }
    this.clear();
    this.pending = pending;
    this.emit({ busy: true, pending: true });
    try {
      const result = await client.request(operation, full);
      if (!this.valid(epoch, client)) return;
      this.release(pending);
      this.publish(result, result.replayed ? "Original receipt returned; current head shown separately. No duplicate mutation." : "Saved Production revision " + result.current.revision + ". No media generated or copied.");
      return result;
    } catch (error) {
      if (this.valid(epoch, client)) {
        if (error.code && safeRejections.has(error.code)) this.release(pending);
        this.failure(error, "Reply unobserved. Command locked; open or reconcile exactly before acting. No automatic retry.");
      }
    }
  }
  async reconcilePending() {
    const pending = this.pending, client = this.client, epoch = this.epoch;
    if (!pending || this.state.busy) return;
    if (!pending.payload) {
      await this.open();
      return;
    }
    if (!this.valid(epoch, client)) return;
    this.emit({ busy: true, pending: true });
    try {
      const result = await client.request(pending.operation, pending.payload);
      if (!this.valid(epoch, client)) return;
      this.release(pending);
      this.publish(result, "Original pending receipt reconciled exactly. Current head shown; no replacement mutation.");
      return result;
    } catch (error) {
      if (this.valid(epoch, client)) this.failure(
        error,
        "Pending reply still unobserved. Command remains locked; no replacement or automatic retry."
      );
    }
  }
  create(fields, identity) {
    return this.mutate("create", fields, identity);
  }
  saveBrief(fields, identity) {
    return this.mutate("update_brief", fields, identity);
  }
  addAsset(kind, intent, identity) {
    return this.mutate("add_asset", { kind, intent, depends_on: [], references: [] }, identity);
  }
  updateAsset(fields, identity) {
    return this.mutate("update_asset", fields, identity);
  }
  addReference(source, label, identity) {
    return this.mutate("add_reference", { request: source.request, take: source.id, label }, identity);
  }
  updateReference(reference, source, label, identity) {
    return this.mutate("update_reference", {
      reference: reference.id,
      request: source.request,
      take: source.id,
      label
    }, identity);
  }
  async link(source, identity) {
    const result = await this.mutate("link_take", { asset: this.state.selectedAsset, request: source.request, take: source.id }, identity);
    if (result && !result.error && this.state.current) this.emit({ selectedTake: source.id });
    return result;
  }
  select(take, identity) {
    return this.mutate("select_take", { asset: this.state.selectedAsset, request: take.request, take: take.id }, identity);
  }
  async loadMethods() {
    const epoch = this.epoch, client = this.client;
    if (!this.valid(epoch, client) || this.state.methodsLoading) return;
    this.emit({ methodsLoading: true, methodsError: false });
    let reader;
    try {
      reader = await openTechnical(this.host, () => this.invalidate(), { namespace: "creation", methods: /* @__PURE__ */ new Set(["methods"]) });
      if (!this.valid(epoch, client)) return;
      const result = await reader.request("methods");
      if (!this.valid(epoch, client)) return;
      if (!result?.kinds) throw Error("Invalid methods envelope");
      this.emit({ methods: result, methodsLoading: false });
    } catch (error) {
      if (this.valid(epoch, client)) {
        this.emit({ methodsLoading: false, methodsError: true });
        if (authorityDenials.has(error.code)) this.failure(error);
      }
    } finally {
      reader?.dispose();
    }
  }
  async loadImportRequests() {
    const epoch = this.epoch, client = this.client;
    if (!this.valid(epoch, client) || this.state.busy) return;
    this.emit({ busy: true });
    let reader;
    try {
      reader = await openTechnical(this.host, () => this.invalidate(), { namespace: "creation", methods: /* @__PURE__ */ new Set(["list"]) });
      if (!this.valid(epoch, client)) return;
      const result = await reader.request("list");
      if (!this.valid(epoch, client)) return;
      this.emit({ importRequests: result.creations || [], busy: false, status: "Choose an existing same-kind request for this import." });
    } catch (error) {
      if (this.valid(epoch, client)) this.failure(error, "Saved requests unavailable. Open the matching chat and refresh requests.");
    } finally {
      reader?.dispose();
    }
  }
  async createWithHermes(asset, direction = asset?.intent, identity = null, append = false) {
    const client = this.client, epoch = this.epoch, current = this.state.current;
    if (!asset || !current || !this.identityValid(identity) || this.state.busy || this.pending) return;
    if (!this.valid(epoch, client) || !this.host.composer?.getDraft || !this.host.composer?.insertText) {
      this.emit({ status: "Open a Hermes chat for this profile, then try again. Nothing sent." });
      return;
    }
    const valid = () => this.valid(epoch, client) && this.state.current?.id === current.id && this.state.current?.revision === current.revision && this.state.selectedAsset === asset.id;
    this.emit({ busy: true });
    try {
      const existing = await this.host.composer.getDraft(client.session);
      if (!valid()) return;
      if (existing && !append) {
        this.emit({ busy: false, draftAsset: asset.id, status: "Your chat has an unsent draft. Choose Add to existing draft to keep it." });
        return;
      }
      const text = "Motion Studio - create " + asset.kind + ' for production "' + current.title + '", asset ' + (asset.position + 1) + ' "' + asset.intent + '": ' + (direction || asset.intent || "Use the production brief.");
      const applied = await insertDraft2(this.host, client.session, text);
      if (!valid()) return;
      this.emit({ busy: false, draftAsset: applied ? null : this.state.draftAsset, status: applied ? "Request added to your chat. Review it and press Send." : "No visible chat composer. Nothing sent." });
      return Boolean(applied);
    } catch {
      if (valid()) this.emit({ busy: false, status: "Chat composer unavailable. Nothing sent." });
    }
  }
  async importTake(file, request, identity = null) {
    const client = this.client, epoch = this.epoch, current = this.state.current;
    const asset = current?.assets.find((item) => item.id === this.state.selectedAsset);
    if (!asset || !this.identityValid(identity) || !this.valid(epoch, client) || this.state.busy || this.pending) return;
    const formats2 = { "image/png": "png", "image/jpeg": "jpeg", "audio/wav": "wav", "audio/x-wav": "wav", "video/mp4": "mp4" };
    const format = formats2[file?.type], kind = format === "png" || format === "jpeg" ? "Image" : format === "mp4" ? "Video" : null;
    if (!format || !file.size || file.size > 16777216) {
      this.emit({ status: "Choose a PNG, JPEG, WAV or MP4 file up to 16 MiB." });
      return;
    }
    if (request && request.kind !== asset.kind || (kind ? kind !== asset.kind : !["Sound effects", "Music", "Voice"].includes(asset.kind))) {
      this.emit({ status: "Choose a file and, if used, an authorized request matching this asset\u2019s media type." });
      return;
    }
    const job = { cancelled: false, id: null, client };
    this.importJob = job;
    const valid = () => this.valid(epoch, client) && this.state.current?.id === current.id && this.state.current?.revision === current.revision && this.state.selectedAsset === asset.id && !job.cancelled;
    this.clear();
    this.emit({ busy: true, importing: true, importProgress: 0, status: "Checking the original file\u2026" });
    try {
      const bytes2 = new Uint8Array(await file.arrayBuffer());
      if (!valid()) return;
      const digest2 = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes2)), (n) => n.toString(16).padStart(2, "0")).join("");
      if (!valid()) return;
      if (!request) {
        request = await client.request("media_import.intent", { production: current.id, expected: current.revision, asset: asset.id, command: command2() });
        if (!valid()) return;
        if (!request?.request || !Number.isInteger(request.revision) || request.kind !== asset.kind || request.method !== "import") throw Error("Import intent could not be confirmed.");
      }
      const begun = await client.request("media_import.begin", {
        command: command2(),
        request: request.request,
        revision: request.revision,
        digest: digest2,
        size: bytes2.length,
        name: file.name,
        format
      });
      job.id = begun.id;
      if (!valid()) {
        if (this.valid(epoch, client)) await client.request("media_import.cancel", { id: job.id });
        return;
      }
      for (let offset = 0; offset < bytes2.length; offset += 196608) {
        const part = bytes2.subarray(offset, offset + 196608);
        let binary = "";
        for (const value of part) binary += String.fromCharCode(value);
        const receipt = await client.request("media_import.chunk", { id: job.id, offset, data: btoa(binary) });
        if (!valid()) return;
        if (receipt.id !== job.id || receipt.received !== offset + part.length) throw Error("Import progress could not be confirmed.");
        this.emit({ importProgress: Math.round(receipt.received / bytes2.length * 100), status: "Importing original\u2026 " + Math.round(receipt.received / bytes2.length * 100) + "%" });
      }
      if (!valid()) return;
      const committed = await client.request("media_import.commit", { id: job.id });
      if (!valid()) return;
      if (committed.take !== begun.take || committed.id !== job.id || committed.status !== "Ready for review") throw Error("Import was not completed.");
      this.emit({ busy: false, importing: false });
      const linked = await this.link({ request: request.request, id: committed.take }, identity);
      if (linked && this.valid(epoch, client) && !this.pending) {
        await this.refresh();
        this.emit({ status: "Imported original linked. Review it, then select it as an output." });
      }
    } catch (error) {
      if (this.valid(epoch, client) && !job.cancelled) this.failure(error, "Import could not be completed. Refresh saved takes before trying again.");
    } finally {
      if (this.importJob === job) {
        this.importJob = null;
        if (this.valid(epoch, client)) this.emit({ busy: false, importing: false });
      }
    }
  }
  async cancelImport() {
    const job = this.importJob;
    if (!job) return;
    job.cancelled = true;
    this.emit({ status: "Cancelling import\u2026" });
    try {
      if (job.id && job.client.current()) await job.client.request("media_import.cancel", { id: job.id });
      if (this.importJob === job) this.emit({ status: "Import cancelled. Refresh saved takes if commit was already in progress." });
    } catch {
      if (this.importJob === job) this.emit({ status: "Cancellation could not be confirmed. Refresh saved takes before retrying." });
    }
  }
  async prepareMediaReview() {
    const current = this.state.current, asset = current?.assets.find((item) => item.id === this.state.selectedAsset), epoch = this.epoch, client = this.client;
    if (!asset || !this.valid(epoch, client) || this.state.busy) return;
    this.clear();
    const serial = this.loadSerial;
    this.loading = true;
    const valid = () => this.valid(epoch, client) && serial === this.loadSerial && this.state.current?.revision === current.revision && this.state.selectedAsset === asset.id;
    this.emit({ busy: true, status: "Checking linked originals\u2026" });
    try {
      const descriptors = [];
      for (const take of asset.takes) {
        const descriptor = await client.request("describe", { production: current.id, asset: asset.id, request: take.request, take: take.id });
        if (!valid()) return;
        const id = descriptor.identity;
        if (!id || id.production !== current.id || id.asset !== asset.id || id.request !== take.request || id.take !== take.id || id.artifact !== take.artifact || id.requestRevision !== take.source_request_revision) throw Error("Media identity could not be verified.");
        descriptors.push(descriptor);
      }
      this.loading = false;
      this.emit({
        busy: false,
        mediaReview: { scope: JSON.stringify([epoch, current.id, current.revision, asset.id, serial]), descriptors, valid, client },
        status: "Originals ready for review. Choose and load a take; nothing plays automatically."
      });
    } catch (error) {
      if (valid()) {
        this.loading = false;
        this.failure(error, "Original media could not be opened. Refresh the linked takes.");
      }
    }
  }
  clearDownload() {
    if (this.downloadURL) URL.revokeObjectURL(this.downloadURL);
    this.downloadURL = null;
    this.emit({ download: null });
  }
  exportHooks() {
    if (this.boundExportHooks) return this.boundExportHooks;
    this.boundExportHooks = { prepare: async (spec, valid) => {
      const client = this.client, descriptor = await client.request("export.prepare", spec);
      const release = () => client.current() ? client.request("export.close", { take: descriptor.take }) : Promise.resolve();
      return {
        descriptor,
        client,
        operation: "export.chunk",
        identity: () => ({ take: descriptor.take }),
        release,
        reauthorize: async () => {
          if (!valid()) throw Error("EXPORT_SCOPE_CHANGED");
          const observed = await client.request("export.descriptor", { take: descriptor.take });
          if (JSON.stringify(observed) !== JSON.stringify(descriptor)) throw Error("EXPORT_INTEGRITY_FAILED");
        }
      };
    }, chooseDestination: async (spec, valid) => ({ write: async (bytes2) => {
      if (!valid()) return { status: "cancelled" };
      if (this.downloadURL) URL.revokeObjectURL(this.downloadURL);
      this.downloadURL = URL.createObjectURL(new Blob([bytes2], { type: spec.mime }));
      this.emit({ download: { url: this.downloadURL, filename: spec.filename } });
      return { status: "ready" };
    } }) };
    return this.boundExportHooks;
  }
  async load(take) {
    const current = this.state.current, asset = this.state.selectedAsset, client = this.client, epoch = this.epoch;
    if (!current || !asset || !this.valid(epoch, client) || this.state.busy) return;
    this.clear();
    const serial = this.loadSerial;
    this.loading = true;
    this.emit({ selectedTake: take.id, busy: true, status: "Checking exact retained original bytes..." });
    try {
      const result = await readRetained(client, "chunk", () => ({
        production: current.id,
        asset,
        request: take.request,
        take: take.id
      }), () => this.valid(epoch, client) && this.state.selectedAsset === asset && serial === this.loadSerial && this.state.selectedTake === take.id && this.state.current?.id === current.id && this.state.current?.revision === current.revision);
      if (!this.valid(epoch, client) || serial !== this.loadSerial || this.state.selectedAsset !== asset || this.state.selectedTake !== take.id || this.state.current?.id !== current.id || this.state.current?.revision !== current.revision) return;
      this.loading = false;
      this.url = URL.createObjectURL(new Blob([result.bytes], { type: "audio/wav" }));
      this.emit({ url: this.url, urlTake: take.id, busy: false, status: "Original retained bytes verified. Listening/download is not delivery proof." });
    } catch (error) {
      if (this.valid(epoch, client) && serial === this.loadSerial) {
        this.loading = false;
        this.failure(
          error,
          ["CREATION_INTEGRITY_FAILED", "RETAINED_SCOPE_CHANGED"].includes(error.message) ? error.message : "RETAINED_BYTES_UNAVAILABLE"
        );
      }
    }
  }
  dispose() {
    this.stopFocusedChat?.();
    this.clear();
    this.disposed = true;
    this.pending = null;
    this.epoch++;
    this.client?.dispose();
  }
};

// studio/native/frontend/comparison-controller.js
var ComparisonController = class {
  constructor(owner, audio, notify = () => {
  }) {
    this.owner = owner;
    this.audio = audio;
    this.notify = notify;
    this.closed = false;
    this.serial = 0;
    this.epoch = owner.epoch;
    this.client = owner.client;
    this.production = owner.state.current.id;
    this.revision = owner.state.current.revision;
    this.asset = owner.state.selectedAsset;
    this.takes = owner.state.current.assets.find((item) => item.id === this.asset).takes;
    this.state = { slots: { A: null, B: null }, active: "A", position: "0", volume: 1, status: "Choose two different retained SFX alternatives. Nothing plays automatically." };
  }
  valid() {
    return !this.closed && this.owner.valid(this.epoch, this.client) && this.owner.state.current?.id === this.production && this.owner.state.current?.revision === this.revision && this.owner.state.selectedAsset === this.asset;
  }
  emit(values) {
    if (this.closed) return;
    Object.assign(this.state, values);
    this.notify({ ...this.state });
  }
  stop() {
    this.serial++;
    this.audio.pause();
  }
  detach() {
    this.stop();
    this.audio.removeAttribute("src");
    this.audio.load();
  }
  drop(slot) {
    const item = this.state.slots[slot];
    if (item?.url) URL.revokeObjectURL(item.url);
  }
  async choose(slot, id) {
    if (!this.valid() || !["A", "B"].includes(slot)) return;
    const take = this.takes.find((item2) => item2.id === id), other = slot === "A" ? "B" : "A";
    if (id && (!take || this.state.slots[other]?.take.id === id)) return;
    this.detach();
    this.drop(slot);
    const item = take ? { take, loading: true, url: null, duration: null } : null;
    this.emit({ slots: { ...this.state.slots, [slot]: item }, status: take ? "Checking exact retained bytes..." : "Comparison slot cleared." });
    if (!item) return;
    const current = () => this.valid() && this.state.slots[slot] === item;
    try {
      const result = await readRetained(this.client, "chunk", () => ({
        production: this.production,
        asset: this.asset,
        request: take.request,
        take: take.id
      }), current);
      if (!current()) return;
      if (result.sha256 !== take.digest || result.bytes.length !== take.size) throw Error("CREATION_INTEGRITY_FAILED");
      item.url = URL.createObjectURL(new Blob([result.bytes], { type: "audio/wav" }));
      item.loading = false;
      this.emit({ status: "Original bytes verified. Load the active slot to measure playback duration; listening is not inferred." });
    } catch (error) {
      if (!current()) return;
      this.drop(slot);
      this.emit({
        slots: { ...this.state.slots, [slot]: { take, loading: false, url: null, duration: null } },
        status: ["CREATION_INTEGRITY_FAILED", "RETAINED_SCOPE_CHANGED"].includes(error.message) ? error.message : "RETAINED_BYTES_UNAVAILABLE"
      });
      this.owner.failure(error, "RETAINED_BYTES_UNAVAILABLE");
    }
  }
  activate(slot) {
    if (!this.valid() || !["A", "B"].includes(slot)) return;
    this.detach();
    this.emit({ active: slot, status: "Slot " + slot + " paused. Press Play explicitly; position is seconds from each original start." });
    const item = this.state.slots[slot];
    if (item?.url) {
      this.audio.src = item.url;
      this.audio.volume = this.state.volume;
      this.audio.load();
    }
  }
  metadata() {
    if (!this.valid()) return;
    const item = this.state.slots[this.state.active];
    if (!item?.url || this.audio.getAttribute("src") !== item.url) return;
    if (!Number.isFinite(this.audio.duration) || this.audio.duration <= 0) {
      this.detach();
      this.emit({ status: "Audio duration unavailable. Playback unavailable." });
      return;
    }
    item.duration = this.audio.duration;
    this.seek(this.state.position);
  }
  position() {
    const text = String(this.state.position).trim();
    return text === "" ? NaN : Number(text);
  }
  seek(value) {
    if (!this.valid()) return;
    this.stop();
    this.emit({ position: String(value) });
    const position = this.position(), item = this.state.slots[this.state.active];
    if (!Number.isFinite(position) || position < 0) {
      this.emit({ status: "Enter a finite position of zero seconds or later. Nothing played." });
      return false;
    }
    if (!item?.duration) {
      this.emit({ status: "Load active slot to measure its duration. Nothing played." });
      return false;
    }
    if (position >= item.duration) {
      this.emit({ status: "Position is at or beyond the end of " + this.state.active + ". No cropping, looping or fallback to zero." });
      return false;
    }
    if (this.audio.getAttribute("src") !== item.url) {
      this.emit({ status: "Load active slot before playback. Nothing played." });
      return false;
    }
    try {
      this.audio.currentTime = position;
      this.emit({ status: "Paused at " + position + " seconds from original start. Press Play explicitly." });
      return true;
    } catch {
      this.emit({ status: "Position unavailable. Nothing played." });
      return false;
    }
  }
  async play() {
    if (!this.valid() || !this.seek(this.state.position)) return;
    const serial = this.serial;
    try {
      await this.audio.play();
      if (!this.valid() || serial !== this.serial) {
        this.audio.pause();
        return;
      }
      this.emit({ status: "Playing " + this.state.active + " from the stated position. No selection or listening approval recorded." });
    } catch {
      if (this.valid() && serial === this.serial) this.emit({ status: "Playback unavailable. Press Play to retry deliberately." });
    }
  }
  pause() {
    if (!this.valid()) return;
    this.stop();
    this.emit({ status: "Paused. Play starts at the entered comparison position." });
  }
  mediaError() {
    if (!this.valid() || !this.audio.getAttribute("src")) return;
    const item = this.state.slots[this.state.active];
    if (item) item.duration = null;
    this.detach();
    this.emit({ status: "Original audio could not be decoded for playback. Nothing played; load deliberately to retry." });
  }
  ended() {
    if (this.valid()) {
      this.stop();
      this.emit({ status: "End of " + this.state.active + ". Other take did not start. Enter a valid position and press Play." });
    }
  }
  volume(value) {
    if (!this.valid()) return;
    const volume = Number(value);
    if (!Number.isFinite(volume) || volume < 0 || volume > 1) return;
    this.audio.volume = volume;
    this.emit({ volume });
  }
  dispose() {
    if (this.closed) return;
    this.detach();
    this.closed = true;
    this.drop("A");
    this.drop("B");
    this.state = { slots: { A: null, B: null }, active: "A", position: "0", volume: 1, status: "" };
    this.takes = [];
  }
};

// studio/native/frontend/production-comparison.js
var plain2 = (text) => String(text).replace(/^Choose two different retained SFX alternatives\..*/, "Choose two different takes. Nothing plays until you press Play.").replace(/^Original bytes verified\..*/, "Take loaded. Choose Listen to hear it.").replace(/active slot/g, "take").replace(/Slot /g, "Take ").replace(/ deliberately/g, "").replace(/Original audio/g, "This take").replace(/entered comparison position/g, "start time you entered");
function ProductionComparison({ controller, asset, identity, onClose, onUse }) {
  const audio = useRef7(null), session = useRef7(null), [state, setState] = useState6(null);
  useEffect7(() => {
    const current = new ComparisonController(controller, audio.current, setState);
    session.current = current;
    const cleanup = () => current.dispose();
    controller.reviewCleanup = cleanup;
    setState({ ...current.state });
    return () => {
      cleanup();
      if (controller.reviewCleanup === cleanup) controller.reviewCleanup = null;
      session.current = null;
    };
  }, [controller]);
  const slots = state?.slots || { A: null, B: null }, active = state?.active || "A";
  const label = (take) => controller.state.available.find((item) => item.id === take.id)?.direction || "Sound effect";
  const takeLabel = (take) => "Take " + (asset.takes.findIndex((item) => item.id === take.id) + 1) + " - " + label(take);
  const button = (label2, action, disabled = false, extra = {}) => h9(Button5, { className: "ms-btn", variant: "outline", onClick: action, disabled, ...extra }, label2);
  return h9(
    "section",
    { "aria-label": "Compare two takes", className: "production-comparison" },
    h9("h3", null, "Compare two takes"),
    h9("p", null, "Comparing only listens. Use take A or B makes that take the one this asset exports."),
    h9("p", null, "Both takes start from 0 seconds at the same volume. Switching pauses playback, and nothing plays until you press Play. The original files are never changed."),
    h9("div", { className: "production-comparison-slots" }, ...["A", "B"].map((slot) => {
      const item = slots[slot], other = slots[slot === "A" ? "B" : "A"];
      return h9(
        "article",
        { key: slot, className: "production-comparison-slot" + (active === slot ? " production-comparison-active" : "") },
        h9("h4", null, "Take " + slot + (active === slot ? " - now listening" : "")),
        h9("label", null, "Take " + slot, h9(
          "select",
          {
            "aria-label": "Comparison take " + slot,
            value: item?.take.id || "",
            onChange: (event) => void session.current?.choose(slot, event.target.value)
          },
          h9("option", { value: "" }, "Choose a take"),
          ...asset.takes.map((take) => h9(
            "option",
            { key: take.id, value: take.id, disabled: take.id === other?.take.id },
            takeLabel(take)
          ))
        )),
        item ? h9(
          "div",
          null,
          h9("p", null, takeLabel(item.take)),
          h9("p", { className: item.take.selected && asset.stale ? "production-stale" : "" }, item.take.selected ? asset.stale ? "Selected, but out of date: the brief or a dependency changed" : "Selected for this asset" : "Not selected"),
          h9("p", null, "Listening review: " + item.take.review),
          h9("p", null, "Audio: " + (item.take.facts?.duration ?? "unknown") + " seconds / " + (item.take.facts?.channels ?? "unknown") + " channels / " + (item.take.facts?.rate ?? "unknown") + " Hz"),
          h9("p", null, item.loading ? "Loading the original..." : item.url ? "Original WAV ready" : "Could not load this take. Choose it again to retry."),
          h9("p", null, "Playback duration: " + (item.duration === null ? "not measured yet" : item.duration.toFixed(3) + " seconds")),
          h9(
            "details",
            null,
            h9("summary", null, "Technical details for " + slot),
            h9("p", null, "Take " + item.take.id + " / source request revision " + item.take.source_request_revision),
            h9("p", null, "Source request " + item.take.request + " / source " + item.take.origin),
            h9("p", null, "Artifact " + item.take.artifact + " / SHA256 " + item.take.digest)
          )
        ) : null,
        h9(
          "div",
          { className: "production-row" },
          button("Listen to " + slot, () => session.current?.activate(slot), !item?.url, { "aria-pressed": active === slot }),
          item ? button("Use take " + slot, () => {
            void controller.select(item.take, identity);
            onUse();
          }, controller.state.busy || controller.state.pending || item.take.selected && !asset.stale) : null
        )
      );
    })),
    h9("label", null, "Position (seconds from the start)", h9("input", {
      type: "number",
      min: 0,
      step: "any",
      "aria-label": "Comparison position seconds",
      value: state?.position ?? "0",
      onChange: (event) => session.current?.seek(event.target.value)
    })),
    h9("label", null, "Same volume for both (loudness is not matched)", h9("input", {
      type: "range",
      min: 0,
      max: 1,
      step: 0.01,
      "aria-label": "Shared monitoring volume",
      value: state?.volume ?? 1,
      onChange: (event) => session.current?.volume(event.target.value)
    })),
    h9("p", null, "Volume " + Math.round((state?.volume ?? 1) * 100) + "% / listening to " + active),
    h9(
      "div",
      {
        tabIndex: 0,
        role: "group",
        className: "production-comparison-player",
        "aria-label": "Comparison keyboard player",
        onKeyDown: (event) => {
          if (event.code === "Space") {
            event.preventDefault();
            if (audio.current.paused) void session.current?.play();
            else session.current?.pause();
          }
        }
      },
      "Listening to take " + active + ". Focus here and press Space to play or pause.",
      h9("audio", {
        ref: audio,
        preload: "metadata",
        "aria-label": "Sound effects A/B comparison audio",
        onLoadedMetadata: () => session.current?.metadata(),
        onEnded: () => session.current?.ended(),
        onError: () => session.current?.mediaError()
      })
    ),
    h9(
      "div",
      { className: "production-row" },
      button("Play " + active, () => void session.current?.play()),
      button("Play from start", () => {
        session.current?.seek("0");
        void session.current?.play();
      }),
      button("Pause", () => session.current?.pause()),
      button("Close comparison", onClose)
    ),
    h9("p", { role: "status", "aria-label": "Comparison status" }, state?.status ? plain2(productionMessage(null, state.status)) : "Opening comparison. Nothing played."),
    h9(
      "details",
      null,
      h9("summary", null, "How comparison works"),
      h9("p", null, "Position is counted in seconds from the start of each take. Nothing is stretched, trimmed or loudness-matched, so real differences in length and level stay audible. Comparing does not mark a take as reviewed.")
    )
  );
}

// studio/native/frontend/production-review.js
var NOTES = { Video: "Cost depends on the selected method and account. Unknown cost is not free; review any spend before sending.", Music: "Local music generation is not qualified yet. You can import a track below." };
var KINDS2 = ["Sound effects", "Music", "Voice", "Image", "Video"];
var two = (value) => String(value).padStart(2, "0");
var originLabel2 = (origin) => origin === "user_import" ? "Imported" : origin === "test_fixture" ? "Test file" : "Generated";
var badge3 = (text, tone2) => text ? h10("span", { className: "ms-badge", "data-tone": tone2 }, text) : null;
var isChosen = (asset, item) => Boolean(item && (item.selected || item.id === asset?.selected_take));
var bars = () => h10("div", { className: "production-wave", "aria-hidden": true }, ...Array.from({ length: 44 }, (_, index) => h10("i", { key: index, style: { height: 18 + Math.round(70 * Math.abs(Math.sin(index * 1.7) * Math.cos(index * 0.45))) + "%" } })));
function ProductionImport({ controller, state, asset, identity }) {
  const input = useRef8(null), [chosen, setChosen] = useState7("");
  useEffect8(() => {
    void controller?.loadImportRequests?.();
  }, [controller, identity.epoch, asset?.id]);
  const requests = (state.importRequests || []).filter((item) => item.kind === asset?.kind);
  const request = requests.find((item) => item.request === chosen) || requests[0];
  return h10(
    "section",
    { className: "production-import", "aria-label": "Import a take" },
    h10("input", {
      ref: input,
      type: "file",
      hidden: true,
      accept: "image/png,image/jpeg,audio/wav,video/mp4",
      "aria-label": "Original media file",
      onChange: (event) => {
        const file = event.target.files?.[0];
        event.target.value = "";
        if (file) void controller.importTake(file, request, identity);
      }
    }),
    h10(Button6, { className: "ms-btn pd-btn pd-wide", variant: "outline", disabled: state.busy || state.pending, onClick: () => input.current?.click() }, "Import a take"),
    h10("p", { className: "ms-help production-center" }, "Made in another tool? Bring it here. PNG, JPEG, WAV or MP4, up to 16 MB."),
    requests.length > 1 ? h10("label", null, "Add it to this request", h10(
      "select",
      {
        "aria-label": "Import saved request",
        value: request?.request || "",
        disabled: state.busy,
        onChange: (event) => setChosen(event.target.value)
      },
      ...requests.map((item) => h10("option", { key: item.request, value: item.request }, item.direction || item.kind + " request"))
    )) : null,
    !requests.length ? h10("p", { className: "ms-help production-center" }, "Import directly into this asset. No sent request or generation is needed.") : null,
    state.importing ? h10(
      "div",
      { className: "production-row" },
      h10("progress", { max: 100, value: state.importProgress || 0, "aria-label": "Import progress" }),
      h10("span", { role: "status" }, " " + (state.importProgress || 0) + "%"),
      h10(Button6, { className: "ms-btn pd-btn", variant: "outline", onClick: () => controller.cancelImport() }, "Cancel import")
    ) : null
  );
}
function ProductionMediaReview({ review, controller, asset, selectedTake, single = false }) {
  const reader = useMemo(() => {
    const options = { client: review.client, valid: () => review.valid() };
    const imported = createImportedReviewReader({ ...options, operation: "media_import.read_chunk" });
    const retained = createRetainedReviewReader({ ...options, operation: "chunk" });
    return (args) => (asset.takes.find((take) => take.id === args.descriptor.identity.take)?.origin === "user_import" ? imported : retained)(args);
  }, [review, asset]);
  const register = useMemo(() => (value) => {
    controller.reviewCleanup = value ? () => value.dispose() : null;
    const selected = review.descriptors.find((item) => item.identity.take === selectedTake) || review.descriptors[0];
    if (value && selected) value.choose("A", selected);
  }, [controller, review, selectedTake]);
  return h10(MediaReview, {
    scope: review.scope,
    descriptors: review.descriptors,
    readBytes: reader,
    isScopeCurrent: review.valid,
    onController: register,
    single
  });
}
function CreatePanel({ state, asset, assets, current, identity, controller, onSection, refineTake = null, onRefineDone = () => {
} }) {
  const [, redraw] = useState7(0), directions = controller.directionDrafts;
  useEffect8(() => {
    if (controller?.loadMethods && !state.methods && !state.methodsError) void controller.loadMethods();
  }, [controller, state.methods, state.methodsError, identity.epoch]);
  const key = (current?.id || "") + ":" + (asset?.id || ""), draft = directions?.get(key), text = draft?.text ?? asset?.intent ?? "";
  const setDraft = (value) => {
    if (!controller.identityValid(identity)) return;
    directions?.set(key, { ...directions.get(key), ...value });
    redraw((count) => count + 1);
  };
  const takes = asset?.takes || [], refining = takes.find((item) => item.id === refineTake) || null;
  const picked = state.methods ? chosenMethod(state.methods, asset?.kind, draft?.method) : null;
  const importing = picked?.id === "import" || picked?.engine === "import" || picked?.action === "import";
  const unavailable = Boolean(draft?.method && (!picked || !picked.available));
  const request = () => [text.trim(), "[Motion Studio context: production " + current.id + ", asset " + asset.id + (refining ? "; refine take " + refining.id + " of request " + refining.request + " as a new take, keeping the earlier one" : "") + ((asset.references || []).length ? "; references " + asset.references.map((ref) => ref.id + " revision " + ref.revision).join(", ") : "") + (picked ? "; preferred method " + picked.id : "") + "]"].join("\n");
  const send = async (append) => {
    if (importing || unavailable) return;
    const sent = directions?.get(key);
    const applied = await controller.createWithHermes(asset, request(), { ...identity, revision: current.revision }, append);
    if (applied && controller.identityValid(identity)) {
      if (directions?.get(key) === sent) directions?.delete(key);
      onRefineDone();
      redraw((count) => count + 1);
    }
  };
  const blocked = state.busy || state.pending, references = (asset?.references || []).map((ref) => (current?.references || []).find((item) => item.id === ref.id)?.label || "Reference");
  return h10(
    "aside",
    { className: "production-create", "aria-label": "Create with Hermes" },
    h10("h2", null, "Create with Hermes"),
    h10("div", { className: "production-kinds", role: "group", "aria-label": "Media type" }, ...KINDS2.map((kind) => {
      const target = assets.find((item) => item.kind === kind), on = asset?.kind === kind;
      return h10("button", {
        key: kind,
        type: "button",
        className: "production-kind",
        "aria-pressed": on,
        disabled: state.busy || !target,
        title: target ? "Show the " + kind + " asset" : "No " + kind + " asset in the plan yet",
        onClick: () => {
          if (!on && target) controller?.chooseAsset(target.id);
        }
      }, kind);
    })),
    !asset ? h10("p", { className: "ms-empty" }, current ? "Add an asset to the plan, then describe what you want here." : "Create a project first.") : h10(
      "div",
      { className: "production-create-body" },
      h10("label", { htmlFor: "production-direction" }, "Direction for " + two(asset.position + 1) + " " + asset.kind),
      h10("textarea", {
        id: "production-direction",
        value: text,
        maxLength: 2e3,
        disabled: state.busy,
        placeholder: "Describe the take you want, e.g. a soft door close with a short room echo",
        onChange: (event) => setDraft({ text: event.target.value })
      }),
      h10(
        "div",
        { className: "production-refs" },
        h10("span", { className: "production-label" }, "References"),
        h10(
          "div",
          { className: "ms-row" },
          ...references.map((label, index) => h10("span", { key: index, className: "ms-chip" }, label)),
          h10("button", { type: "button", className: "ms-chip production-chip-add", onClick: () => onSection("References") }, "+ Add")
        )
      ),
      refining ? h10(
        "p",
        { className: "ms-row production-refining" },
        h10("span", { className: "ms-chip", "data-on": "true" }, "Refining take " + two(takes.indexOf(refining) + 1)),
        h10("button", { type: "button", className: "production-linkish", onClick: onRefineDone }, "Start fresh instead")
      ) : null,
      state.methods ? h10(MethodPicker, {
        methods: state.methods,
        kind: asset.kind,
        choice: draft?.method,
        idPrefix: "production-method",
        onChoose: (id) => setDraft({ method: id })
      }) : null,
      state.methodsError ? h10("p", { role: "status" }, "Method information unavailable. ", h10("button", {
        type: "button",
        disabled: state.methodsLoading,
        onClick: () => controller.loadMethods()
      }, "Retry methods")) : null,
      state.methodsLoading ? h10("p", { role: "status" }, "Checking methods. Nothing is started.") : null,
      NOTES[asset.kind] ? h10("p", { className: "ms-help production-kind-note", role: "note" }, NOTES[asset.kind]) : null,
      h10(Button6, {
        className: "ms-btn pd-btn pd-primary pd-wide",
        disabled: blocked || !text.trim() || importing || unavailable,
        onClick: () => send(false)
      }, "Create with Hermes"),
      importing ? h10("p", { className: "ms-help" }, "Import is not generation. Use Import a take below to choose an existing file.") : null,
      state.draftAsset === asset.id ? h10(Button6, {
        className: "ms-btn pd-btn pd-wide",
        variant: "outline",
        disabled: blocked || !text.trim() || importing || unavailable,
        onClick: () => send(true)
      }, "Add to existing draft") : null,
      h10("p", { className: "ms-help production-center" }, "Puts a request in your Hermes chat. You review it and press Send."),
      h10("hr", { className: "production-rule" }),
      h10(ProductionImport, { controller, state, asset, identity }),
      h10("hr", { className: "production-rule" }),
      h10("p", { className: "ms-help production-center" }, "References and original takes stay with the project.")
    )
  );
}
function Stage({ state, asset, take, index, audio, controller, current, onUse, onClose, identity, single }) {
  if (state.comparisonOpen) return h10(ProductionComparison, { key: state.scopeEpoch + ":" + asset.id + ":" + current.revision, controller, asset, identity, onUse, onClose });
  if (state.mediaReview) return h10(
    "div",
    { className: "production-viewer production-viewer-open" },
    h10(ProductionMediaReview, { review: state.mediaReview, controller, asset, selectedTake: state.selectedTake, single })
  );
  if (!take) return h10(
    "div",
    { className: "production-viewer" },
    h10("p", { className: "production-viewer-title" }, "No takes yet"),
    h10("p", { className: "production-muted" }, "Use Create with Hermes to ask for one, or import a file you already have.")
  );
  const loaded = state.url && state.urlTake === take.id, sound = asset.kind !== "Image" && asset.kind !== "Video";
  return h10(
    "div",
    { className: "production-viewer" },
    sound ? bars() : h10("div", { className: "production-frame", "aria-hidden": true }),
    h10("p", { className: "production-viewer-title" }, "Take " + two(index + 1) + " / " + asset.kind),
    loaded ? h10(
      "div",
      { className: "production-player" },
      h10("audio", { ref: audio, controls: true, src: state.url, "aria-label": "Selected take audio" }),
      h10("a", { className: "ms-link", href: state.url, download: "motion-studio-production-original.wav" }, "Save / download original WAV")
    ) : h10("p", { className: "production-muted" }, "Nothing plays until you press Play.")
  );
}
function ProductionReview({ state, asset, take, button, identity, audio, controller, onRefine }) {
  const compareButton = useRef8(null), restoreFocus = useRef8(false), current = state.current, busy = state.busy, [single, setSingle] = useState7(true);
  useEffect8(
    () => {
      if (restoreFocus.current && !state.comparisonOpen && !busy) {
        restoreFocus.current = false;
        compareButton.current?.focus();
      }
    },
    [state.comparisonOpen, busy]
  );
  if (!asset) return h10("section", { className: "production-review", "aria-label": "Review" }, h10(
    "div",
    { className: "production-viewer" },
    h10("p", { className: "production-viewer-title" }, current ? "No assets yet" : "No project open"),
    h10("p", { className: "production-muted" }, current ? "Open Plan and add the first thing this project needs." : "Open a project or write a brief to start one.")
  ));
  const takes = asset.takes || [], index = take ? takes.findIndex((item) => item.id === take.id) : -1, chosen = isChosen(asset, take);
  const stale = Boolean(asset.stale && chosen), loaded = take && state.url && state.urlTake === take.id;
  const playable = take && asset.kind === "Sound effects" && take.origin !== "user_import";
  const play = () => {
    if (!loaded) return controller.load(take);
    const node = audio.current;
    if (node) void (node.paused ? node.play() : node.pause());
  };
  const viewerOpen = Boolean(state.mediaReview || state.comparisonOpen);
  return h10(
    "section",
    { className: "production-review", "aria-label": "Review" },
    h10("h2", { className: "production-title" }, h10("span", { className: "production-title-n" }, two(asset.position + 1) + " /"), " " + (asset.intent || asset.kind)),
    h10("p", { className: "production-muted production-sub" }, asset.kind + " - " + (takes.length === 1 ? "1 take" : takes.length + " takes")),
    h10(Stage, {
      state,
      asset,
      take,
      index,
      audio,
      controller,
      current,
      identity,
      single,
      onUse: () => {
        restoreFocus.current = true;
      },
      onClose: () => {
        restoreFocus.current = true;
        controller.clear();
      }
    }),
    take ? h10(
      "div",
      { className: "production-statusline" },
      viewerOpen ? button("Close viewer", () => controller.clear()) : playable ? button(loaded ? "Play / pause" : "Play", play) : button("Open viewer", () => {
        setSingle(true);
        controller.prepareMediaReview();
      }),
      h10("span", { className: "production-take-state", "data-on": String(chosen) }, "Take " + two(index + 1) + (chosen ? " - Selected" : " - Not selected")),
      badge3(take.review || "Not reviewed", take.review === "Approved" ? "good" : void 0),
      badge3(originLabel2(take.origin)),
      stale ? badge3("Out of date", "warn") : null
    ) : null,
    take ? h10(TakeChecks, { key: take.id, host: controller.host, request: take.request, take, onChanged: () => controller.refresh() }) : null,
    h10(
      "div",
      { className: "production-takes-head" },
      h10("h3", { className: "ms-section-title" }, "Takes"),
      h10(
        "div",
        { className: "production-row" },
        h10(Button6, {
          className: "ms-btn pd-btn",
          variant: "outline",
          ref: compareButton,
          disabled: busy || state.pending || takes.length < 2,
          onClick: () => {
            setSingle(false);
            if (asset.kind === "Sound effects") controller.compare();
            else controller.prepareMediaReview();
          }
        }, "Compare"),
        button(stale ? "Keep this take" : "Use take", () => controller.select(take, identity), !take || chosen && !asset.stale),
        button("Refine", onRefine, !take)
      )
    ),
    takes.length ? h10("div", { className: "production-takes", role: "group", "aria-label": "Takes for this asset" }, ...takes.map((item, position) => {
      const on = isChosen(asset, item);
      return h10(
        "button",
        {
          key: item.id,
          type: "button",
          className: "production-take",
          "aria-pressed": item.id === take?.id,
          "data-selected": String(on),
          disabled: busy,
          onClick: () => controller.chooseTake(item.id)
        },
        h10("span", { className: "production-take-thumb", "aria-hidden": true }, bars()),
        h10("span", { className: "production-take-name" }, "Take " + two(position + 1) + (on ? " - Selected" : "")),
        h10(
          "span",
          { className: "ms-meta" },
          badge3(item.review || "Not reviewed", item.review === "Approved" ? "good" : void 0),
          badge3(originLabel2(item.origin)),
          on && asset.stale ? badge3("Out of date", "warn") : null
        )
      );
    })) : h10("p", { className: "ms-empty" }, "Takes for this asset appear here."),
    h10("p", { className: "ms-help" }, "Compare puts two takes side by side without changing anything. Use take makes the open take the one this asset exports. Refine starts a follow-up request for the open take in Create with Hermes."),
    take ? h10(
      "details",
      { className: "ms-tech" },
      h10("summary", null, "Technical details"),
      h10("p", null, "Take " + take.id),
      take.artifact ? h10("p", null, "File " + take.artifact) : null,
      h10("p", null, "Source: " + (take.origin || "unknown") + (take.source_request_revision ? " / request revision " + take.source_request_revision : ""))
    ) : null
  );
}

// studio/native/frontend/production-page.js
var KINDS3 = ["Sound effects", "Music", "Voice", "Image", "Video"];
var SECTIONS = ["Review", "Brief", "Plan", "References", "Outputs"];
var emptyBrief = { text: "", purpose: "", audience: "", usage: "" };
var sameBrief = (a, b) => a.title === b.title && Object.keys(emptyBrief).every((key) => a.brief[key] === b.brief[key]);
var PLAIN2 = [
  [/^Saved Production reopened\..*/, "Project opened."],
  [/^Saved Production observed\..*/, "Project is up to date."],
  [/^Open a saved Production or create a brief\..*/, "Open a project or start a new one."],
  [/^New Production brief\..*/, "New project. Write a brief to begin."],
  [/^Checking exact retained original bytes.*/, "Checking the original file..."],
  [/^Original retained bytes verified\..*/, "Original ready. Press play on the player."],
  [/^Unresolved Create.*|^Uncertain command locked\..*/, "A project was being saved when the connection dropped. Choose Check interrupted save."],
  [/^Lost Create reconciled.*/, "The interrupted save was found. Nothing was duplicated."],
  [/^Stale visual scope rejected\..*/, "The project changed. Reopen it and try again."],
  [/^Reviewed Production management associated\..*/, "This chat is connected."],
  [/^Selected chat\/profile\/connection changed\..*/, "The selected chat changed. Reopen the project."],
  [/^Imported original linked\..*/, "Import finished. Review the take, then choose Use take."],
  [/^Choose an existing same-kind request for this import\./, "Ready."],
  [/^Durable Create recovery marker unavailable\..*/, "This window cannot save safely right now. Nothing was sent."],
  [/^Choose an existing authorized request and file.*/, "Choose a file that matches this asset\u2019s media type."],
  [/^[A-Z0-9_-]{4,}$/, "Something went wrong. Refresh the project and try again."]
];
function plainStatus(status) {
  const text = workspaceStatus(status), match = PLAIN2.find(([pattern]) => pattern.test(text));
  return match ? match[1] : text;
}
function MoreMenu({ children }) {
  const node = useRef9(null);
  useEffect9(() => {
    const outside = (event) => {
      if (node.current?.open && !node.current.contains(event.target)) node.current.open = false;
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, []);
  return h11(
    "details",
    { ref: node, className: "ms-more", onKeyDown: (event) => {
      if (event.key !== "Escape" || !node.current?.open) return;
      node.current.open = false;
      node.current.querySelector("summary")?.focus();
    } },
    h11("summary", { className: "pd-btn pd-ghost" }, "More"),
    h11("div", { className: "ms-row ms-more-body", onClick: (event) => {
      if (event.target.closest?.("button") && node.current) node.current.open = false;
    } }, children)
  );
}
function ProjectBar({ state, current, busy, section, button, controller, onNew, onSection }) {
  return h11(
    "div",
    { className: "production-bar" },
    state.productions.length ? h11("label", { className: "production-project" }, h11("span", null, "Project"), h11(
      "select",
      {
        "aria-label": "Project",
        value: current?.id || "",
        disabled: busy,
        onChange: (event) => void controller.current?.open(event.target.value)
      },
      current ? null : h11("option", { value: "", disabled: true }, "New project"),
      ...state.productions.map((item) => h11("option", { key: item.id, value: item.id }, item.title || "Untitled project"))
    )) : h11("p", { className: "production-project" }, h11("span", null, "Project"), h11("strong", null, "New project")),
    current ? button("New project", onNew) : null,
    state.pending ? button("Check interrupted save", () => controller.current?.reconcilePending(), false, true) : null,
    h11("div", { className: "ms-spacer" }),
    h11(
      MoreMenu,
      null,
      button("Refresh", () => controller.current?.refresh(), false, true),
      button("Reopen project", () => controller.current?.open(current?.id), false, true),
      button(state.connecting ? "Connecting\u2026" : "Connect this chat", () => controller.current?.admit())
    ),
    current && section !== "Outputs" ? h11(Button7, {
      className: "ms-btn pd-btn pd-accent",
      variant: "outline",
      title: "Choose what to package and save it as one ZIP",
      onClick: () => onSection("Outputs")
    }, "Export assets") : null
  );
}
function BriefPanel({ brief, current, busy, button, setBrief, setBriefField, saveBrief, createProduction, discard, focusRequest }) {
  const panel = useRef9(null), ready = Boolean(brief.title.trim() && brief.brief.text.trim());
  useEffect9(() => {
    if (!focusRequest) return;
    const input = panel.current?.querySelector('[aria-label="Production title"]');
    input?.scrollIntoView({ block: "center", behavior: "smooth" });
    input?.focus({ preventScroll: true });
  }, [focusRequest]);
  return h11(
    "section",
    { ref: panel, className: "ms-panel production-panel", "aria-label": "Brief editor" },
    h11("h2", null, current ? "Brief" : "Start a project"),
    h11("p", { className: "production-muted" }, "A title and a short brief are enough. The other fields are optional context. Saving never starts generation."),
    h11("label", null, "Project title", h11(Input3, {
      "aria-label": "Production title",
      value: brief.title,
      maxLength: 200,
      disabled: busy,
      placeholder: "e.g. Morning ritual",
      onChange: (event) => setBrief("title", event.target.value)
    })),
    ...[["text", "Brief"], ["purpose", "Purpose (optional)"], ["audience", "Audience (optional)"], ["usage", "Usage (optional)"]].map(([key, label]) => h11("label", { key }, label, h11(Textarea4, {
      "aria-label": label,
      value: brief.brief[key],
      maxLength: key === "text" ? 8e3 : 2e3,
      disabled: busy,
      className: key === "text" ? "" : "production-short",
      onChange: (event) => setBriefField(key, event.target.value)
    }))),
    h11(
      "div",
      { className: "production-row" },
      current ? button("Save brief", saveBrief, false, false, true) : button("Create project", createProduction, !ready, false, true, { "aria-describedby": !ready ? "production-create-hint" : void 0 }),
      button("Discard changes", discard)
    ),
    !current && !ready ? h11("p", { id: "production-create-hint", className: "ms-help" }, "Enter a title and a brief to create your project.") : null,
    current ? null : h11("p", { className: "ms-help" }, "A new project starts with one asset for each media type. You can add, edit or ignore them in Plan."),
    current ? h11(
      "details",
      { className: "ms-tech" },
      h11("summary", null, "Technical details"),
      h11("p", null, "Project revision " + current.revision + " / brief revision " + current.brief_revision)
    ) : null
  );
}
function ReferencesPanel({ state, current, asset, source, referenceLabel, busy, button, controller, identity, setSource, setLabel }) {
  return h11(
    "section",
    { className: "ms-panel production-panel", "aria-label": "References" },
    h11("h2", null, "References"),
    h11("p", { className: "production-muted" }, "Bring a take you saved in Quick Create into this project, as a take for the selected asset or as a reference that keeps later takes consistent."),
    state.available.length ? h11("label", null, "Saved take from Quick Create", h11(
      "select",
      {
        "aria-label": "Retained Quick Create take",
        value: source?.id || "",
        disabled: busy,
        onChange: (event) => setSource(event.target.value)
      },
      ...state.available.map((item) => h11("option", { key: item.id, value: item.id }, item.direction))
    )) : h11("p", { className: "ms-empty" }, "No saved Quick Create takes in this chat yet."),
    source ? h11("p", { className: "ms-meta" }, h11("span", { className: "ms-badge" }, source.kind), h11("span", { className: "ms-badge" }, source.review)) : null,
    current && source ? h11(
      "div",
      { className: "production-ref-actions" },
      h11(
        "div",
        null,
        button("Add as a take for the selected asset", () => controller.current?.link(source, identity), !asset || source.kind !== asset.kind),
        asset && source.kind !== asset.kind ? h11("p", { className: "ms-help" }, "The selected asset is " + asset.kind + "; this take is " + source.kind + ".") : null
      ),
      h11("label", null, "Reference name", h11(Input3, {
        "aria-label": "Reference label",
        value: referenceLabel,
        maxLength: 200,
        disabled: busy,
        placeholder: "e.g. Cafe ambience",
        onChange: (event) => setLabel(event.target.value)
      })),
      h11("div", null, button("Save as reference", () => controller.current?.addReference(source, referenceLabel, identity)))
    ) : null,
    (current?.references || []).length ? h11("h3", { className: "ms-section-title production-gap" }, "Project references") : null,
    ...(current?.references || []).map((reference) => h11(
      "article",
      { key: reference.id, className: "production-ref" },
      h11("div", null, h11("h3", null, reference.label || "Reference"), h11("p", { className: "ms-meta" }, h11("span", { className: "ms-badge" }, reference.take.review || "Not reviewed"))),
      source ? button("Replace with chosen take", () => controller.current?.updateReference(
        reference,
        source,
        referenceLabel || reference.label,
        identity
      )) : null,
      h11(
        "details",
        { className: "ms-tech" },
        h11("summary", null, "Technical details"),
        h11("p", null, "Reference revision " + reference.revision + " / take " + reference.take.id)
      )
    ))
  );
}
function OutputsPanel({ state, assets, controller }) {
  return h11(
    "section",
    { className: "ms-panel production-panel", "aria-label": "Outputs" },
    h11("h2", null, "Outputs"),
    h11("p", { className: "production-muted" }, "The take you chose for each asset. Only chosen, up-to-date takes can be exported."),
    assets.length ? h11("ul", { className: "production-outputs" }, ...assets.map((item) => {
      const index = (item.takes || []).findIndex((take) => take.id === item.selected_take);
      return h11(
        "li",
        { key: item.id },
        h11("span", { className: "production-out-name" }, kindIcon(item.kind), item.position + 1 + ". " + item.kind),
        h11("span", { className: "ms-badge", "data-tone": !item.selected_take ? void 0 : item.stale ? "warn" : "good" }, !item.selected_take ? "No take chosen" : item.stale ? "Out of date - review again" : index < 0 ? "Take chosen" : "Take " + (index + 1) + " chosen")
      );
    })) : h11("p", { className: "ms-empty" }, "Add assets in Plan to see them here."),
    h11(ProductionExport, { owner: controller.current, productionState: state, hooks: controller.current?.exportHooks?.() })
  );
}
function PlanRail({ section, showSection, assets, asset, busy, current, controller }) {
  return h11(
    "div",
    { className: "production-left" },
    h11(
      "nav",
      { className: "production-sections", "aria-label": "Production sections" },
      ...SECTIONS.map((name) => h11("button", { key: name, type: "button", "aria-pressed": section === name, onClick: () => showSection(name) }, name))
    ),
    current ? h11(
      "div",
      { className: "production-rail-plan" },
      h11(
        "div",
        { className: "production-rail-head" },
        h11("h2", { className: "ms-section-title" }, "Asset plan"),
        h11("button", { type: "button", className: "production-linkish", onClick: () => showSection("Plan") }, "Edit plan")
      ),
      h11(ProductionBoard, { assets, selectedAsset: asset?.id, busy, references: current.references || [], onChooseAsset: (id) => controller.current?.chooseAsset(id) })
    ) : null
  );
}
function useDrafts() {
  const [briefDraft, setBriefDraft] = useState8({ key: null }), [assetDraft, setAssetDraft] = useState8({ key: null });
  const [sourceDraft, setSourceDraft] = useState8({ key: null, id: "" }), [referenceDraft, setReferenceDraft] = useState8({ key: null, text: "" });
  const [kindDraft, setKindDraft] = useState8({ key: null, kind: KINDS3[0] }), [intentDraft, setIntentDraft] = useState8({ key: null, text: "" });
  const [sectionDraft, setSectionDraft] = useState8({ key: null, name: "Review" }), [helpOpen, setHelpOpen] = useState8(false), [refine, setRefine] = useState8({ key: null, take: null });
  return {
    refine,
    setRefine,
    briefDraft,
    setBriefDraft,
    assetDraft,
    setAssetDraft,
    sourceDraft,
    setSourceDraft,
    referenceDraft,
    setReferenceDraft,
    kindDraft,
    setKindDraft,
    intentDraft,
    setIntentDraft,
    sectionDraft,
    setSectionDraft,
    helpOpen,
    setHelpOpen
  };
}
function ProductionPage({ createController, onQuickCreate, onTools }) {
  const controller = useRef9(null), audio = useRef9(null), [state, setState] = useState8(null), [notice, setNotice] = useState8(null), d = useDrafts();
  useEffect9(() => {
    const current2 = createController(setState);
    controller.current = current2;
    setState({ ...current2.state });
    void current2.open();
    return () => {
      audio.current?.pause();
      current2.dispose();
      controller.current = null;
    };
  }, [createController]);
  useEffect9(() => {
    if (!state?.url) audio.current?.pause();
  }, [state?.url, state?.urlTake, state?.scopeEpoch]);
  if (!state) return h11("p", null, "Production - no work started.");
  const current = state.current, busy = state.busy, assets = current?.assets || [];
  const asset = assets.find((item) => item.id === state.selectedAsset) || assets[0];
  const take = asset?.takes.find((item) => item.id === state.selectedTake) || null;
  const briefKey = state.scopeEpoch + ":" + (current?.id || "new");
  const section = !current ? "Brief" : d.sectionDraft.key === briefKey ? d.sectionDraft.name : "Review";
  const identity = { epoch: state.scopeEpoch, production: current?.id || null, asset: asset?.id };
  const source = state.available.find((item) => item.id === (d.sourceDraft.key === briefKey ? d.sourceDraft.id : "")) || state.available[0];
  const referenceLabel = d.referenceDraft.key === briefKey ? d.referenceDraft.text : "";
  const newKind = d.kindDraft.key === briefKey ? d.kindDraft.kind : KINDS3[0], newIntent = d.intentDraft.key === briefKey ? d.intentDraft.text : "";
  const brief = d.briefDraft.key === briefKey ? d.briefDraft : {
    key: briefKey,
    baseRevision: current?.revision || 0,
    title: current?.title || "",
    brief: { ...emptyBrief, ...current?.brief }
  };
  const assetKey = briefKey + ":" + (asset?.id || "none");
  const assetValues = d.assetDraft.key === assetKey ? d.assetDraft : {
    key: assetKey,
    baseRevision: current?.revision || 0,
    intent: asset?.intent || "",
    position: asset?.position || 0,
    depends_on: asset?.depends_on || [],
    references: (asset?.references || []).map((ref) => ref.id)
  };
  const setAssetValues = (values) => d.setAssetDraft({ ...assetValues, ...values });
  const button = (label, action, disabled = false, always = false, primary = false, props = {}) => h11(Button7, {
    ...props,
    className: "ms-btn pd-btn" + (primary ? " pd-primary" : ""),
    variant: primary ? "default" : "outline",
    disabled: busy || !always && state.pending || disabled,
    onClick: action
  }, label);
  const showSection = (name) => {
    setNotice(null);
    if (name !== section) controller.current?.clear();
    d.setSectionDraft({ key: briefKey, name });
  };
  const saveBrief = async () => {
    const submitted = brief, result = await controller.current?.saveBrief({
      title: submitted.title,
      brief: submitted.brief,
      expected: submitted.baseRevision
    }, identity);
    if (!result?.receipt) return;
    d.setBriefDraft((draft) => {
      if (draft.key !== briefKey) return draft;
      return sameBrief(draft, submitted) ? { key: null } : { ...draft, baseRevision: result.receipt.revision };
    });
  };
  const saveAsset = async () => {
    const submitted = assetValues, result = await controller.current?.updateAsset({
      asset: asset.id,
      kind: asset.kind,
      intent: submitted.intent,
      position: submitted.position,
      depends_on: submitted.depends_on,
      references: submitted.references,
      expected: submitted.baseRevision
    }, identity);
    if (!result?.receipt) return;
    d.setAssetDraft((draft) => {
      if (draft.key !== assetKey) return draft;
      const unchanged = JSON.stringify(draft) === JSON.stringify(submitted);
      return unchanged ? { key: null } : { ...draft, baseRevision: result.receipt.revision };
    });
  };
  const createProduction = async () => {
    if (!brief.title.trim() || !brief.brief.text.trim()) return;
    setNotice(null);
    const owner = controller.current, result = await owner?.create({ title: brief.title, brief: brief.brief, kinds: KINDS3 }, identity);
    const saved = owner?.state.current;
    if (result?.receipt && controller.current === owner && owner.state.scopeEpoch === identity.epoch && saved) {
      const key = identity.epoch + ":" + saved.id;
      d.setBriefDraft({ key: null });
      d.setSectionDraft({ key, name: "Plan" });
      setNotice({ key, text: "Project created." });
    }
  };
  const refine = () => {
    d.setRefine({ key: assetKey, take: take?.id || null });
    const box = document.getElementById("production-direction");
    box?.scrollIntoView({ block: "nearest" });
    box?.focus();
  };
  const panel = section === "Brief" ? h11(BriefPanel, {
    brief,
    current,
    busy,
    button,
    saveBrief,
    createProduction,
    discard: () => d.setBriefDraft({ key: null }),
    focusRequest: notice?.key === briefKey ? notice.focusRequest : null,
    setBrief: (key, value) => d.setBriefDraft({ ...brief, [key]: value }),
    setBriefField: (key, value) => d.setBriefDraft({ ...brief, brief: { ...brief.brief, [key]: value } })
  }) : section === "Plan" ? h11(ProductionPlan, {
    assets,
    asset,
    current,
    busy,
    controller,
    briefKey,
    newKind,
    newIntent,
    setKindDraft: d.setKindDraft,
    setIntentDraft: d.setIntentDraft,
    identity,
    assetValues,
    setAssetValues,
    saveAsset,
    setAssetDraft: d.setAssetDraft,
    button
  }) : section === "References" ? h11(ReferencesPanel, {
    state,
    current,
    asset,
    source,
    referenceLabel,
    busy,
    button,
    controller,
    identity,
    setSource: (id) => d.setSourceDraft({ key: briefKey, id }),
    setLabel: (text) => d.setReferenceDraft({ key: briefKey, text })
  }) : section === "Outputs" ? h11(OutputsPanel, { state, assets, controller }) : h11(ProductionReview, { state, asset, take, button, identity, audio, controller: controller.current, onRefine: refine });
  return h11(
    "section",
    { className: "ms production-shell", "aria-label": "Production workspace" },
    h11("style", null, productionStyles),
    h11(
      "div",
      { className: "ms-inner" },
      h11(MotionHeader, {
        active: "production",
        onCreate: onQuickCreate,
        onProduction: () => {
        },
        onTools,
        status: plainStatus(state.status),
        helpOpen: d.helpOpen,
        onHelp: () => d.setHelpOpen(!d.helpOpen)
      }),
      h11(HelpPanel, { open: d.helpOpen, onClose: () => d.setHelpOpen(false), title: "Production", guide: PRODUCTION_HELP.guide }),
      state.needsConnection || state.connectionStatus ? h11(
        "div",
        { className: "ms-notice", "aria-label": "Chat connection" },
        h11("p", { "aria-live": "polite" }, state.connectionStatus || "Connect this chat to use its Production workflow."),
        button(state.connecting ? "Connecting\u2026" : "Connect this chat", () => controller.current?.admit(), false, false, true)
      ) : null,
      h11(
        "div",
        { className: "production-body" },
        h11(ProjectBar, {
          state,
          current,
          busy,
          section,
          button,
          controller,
          onSection: showSection,
          onNew: () => {
            if (busy || state.pending) return;
            controller.current?.newBrief();
            const key = state.scopeEpoch + ":new";
            d.setBriefDraft({ key: null });
            d.setSectionDraft({ key, name: "Brief" });
            setNotice({ key, focusRequest: {}, text: "New project \u2014 give it a title and a brief, then Create project." });
          }
        }),
        notice?.key === briefKey ? h11("p", { className: "production-notice", role: "status" }, notice.text) : null,
        current ? h11("details", { className: "production-howto" }, h11("summary", null, "How Production works"), h11(QuickHelp, { steps: PRODUCTION_HELP.quick })) : h11(QuickHelp, { steps: PRODUCTION_HELP.quick }),
        h11(
          "div",
          { className: "production-layout", "data-project": String(Boolean(current)) },
          current ? h11(PlanRail, { section, showSection, assets, asset, busy, current, controller }) : null,
          h11("main", { className: "production-main", "aria-label": "Production " + section }, panel),
          current ? h11(CreatePanel, {
            state,
            asset,
            assets,
            current,
            identity,
            controller: controller.current,
            onSection: showSection,
            refineTake: d.refine.key === assetKey ? d.refine.take : null,
            onRefineDone: () => d.setRefine({ key: null, take: null })
          }) : null
        )
      )
    )
  );
}

// studio/native/frontend/director-page.js
import { createElement as h12, useEffect as useEffect10, useRef as useRef10, useState as useState9 } from "react";
var styles = `.director-page{background:var(--ui-bg-primary,#151816)!important}.director-page p{margin-bottom:12px}.director-page .ms-btn{background:var(--ui-bg-secondary,#26332c);color:var(--ms-text);border:1px solid var(--ms-line);font:inherit;cursor:pointer;margin:4px 8px 4px 0;padding:8px 12px}.director-page button:disabled{opacity:.55;cursor:not-allowed}.director-grid{display:grid;grid-template-columns:minmax(220px,1fr) minmax(0,2fr);gap:24px}.director-grid>*{min-width:0}.director-page p,.director-page button{overflow-wrap:anywhere}.director-page label{display:block;margin:12px 0}.director-page input,.director-page textarea{display:block;width:100%;box-sizing:border-box;background:var(--ui-bg-secondary,#26332c);color:inherit;border:1px solid var(--ms-line);padding:12px}.director-page dialog{max-width:min(480px,85vw);background:var(--ui-bg-secondary,#26332c);color:var(--ms-text);border:1px solid var(--ms-line);padding:24px}.director-page button:focus-visible{outline:2px solid var(--ui-focus-border,var(--ui-accent));outline-offset:4px}@media(max-width:650px){.director-grid{display:block}.director-detail{margin-top:24px}}`;
var HELP = "Rescan reads cached metadata and fixed PATH presence only. Skills are instructions, not tested tools. Learn this tool drafts research into your selected chat; review costs under its budget and press Send. Research never authorizes generation. Test and enable runs one disclosed tiny local call and activates only its tested operation/version/shape/length after usable bytes and applicable Crystal Ball checks. Unknown cost is not free. Missing senses remain visible. Crystal Ball PASS is not your approval. Export assets is an originals ZIP with check coverage, not an assembled movie. Delete from Studio hides only inactive, unreferenced entries; Undo/Restore keep the same originals, history, reviews and reports across restart. In-use takes need a different selection or reference removal; unresolved runs need stop/reconciliation.";
function Confirmation({ card, onCancel, onConfirm, busy }) {
  const dialog = useRef10(null), previous = useRef10(null);
  useEffect10(() => {
    previous.current = document.activeElement;
    dialog.current?.showModal();
    return () => previous.current?.focus?.();
  }, []);
  return h12(
    "dialog",
    { ref: dialog, "aria-label": "Confirm tiny test", onCancel: (event) => {
      event.preventDefault();
      onCancel();
    } },
    h12("h2", null, "Test and enable " + card.name + "?"),
    h12("p", null, "One call: " + card.operation + ". Harmless test input: " + card.shape + ". Output: one tiny retained file."),
    h12("p", null, "Local process and output only; no install or authorized network use. " + card.price + ". " + card.wait + ". Crystal Ball checks may take up to 60 more seconds."),
    h12("p", null, "Enable only this operation, pinned version, tested shape and " + (card.seconds || 0) + " second length. Your review stays Not reviewed. No second activation or automatic retry."),
    h12(
      "div",
      { className: "ms-row" },
      h12("button", { type: "button", className: "ms-btn", disabled: busy, onClick: onConfirm }, "Test and enable"),
      h12("button", { type: "button", className: "ms-btn", disabled: busy, onClick: onCancel, autoFocus: true }, "Cancel")
    )
  );
}
function DirectorPage({ createController, onBack }) {
  const current = useRef10(null), [state, setState] = useState9(null), [selected, setSelected] = useState9(null), [name, setName] = useState9(""), [documentation, setDocs] = useState9(""), [help, setHelp] = useState9(""), [confirm, setConfirm] = useState9(null), [showHelp, setShowHelp] = useState9(false);
  useEffect10(() => {
    const controller = createController(setState);
    current.current = controller;
    setState({ ...controller.state });
    void controller.open();
    return () => {
      controller.dispose();
      current.current = null;
    };
  }, [createController]);
  useEffect10(() => {
    setConfirm(null);
    setSelected(null);
    setName("");
    setDocs("");
    setHelp("");
  }, [state?.scopeEpoch]);
  if (!state) return h12("p", null, "Opening tools\u2026");
  const card = state.cards.find((item) => item.id === selected), busy = state.busy, c = current.current;
  const button = (label, action, disabled = false) => h12("button", { type: "button", className: "ms-btn", disabled: busy || disabled, onClick: action }, label);
  return h12("section", { className: "ms director-page" }, h12("style", null, creationStyles + styles), h12(
    "div",
    { className: "ms-inner" },
    h12(
      "header",
      { className: "ms-top" },
      h12("h1", null, "Tools"),
      button("Back to workspace", onBack),
      button("Rescan", () => c.open()),
      button(showHelp ? "Close help" : "Help", () => setShowHelp(!showHelp))
    ),
    h12("p", { role: "status", "aria-live": "polite" }, state.status),
    h12("p", null, "Profile: " + (state.inventory?.profile || "Unavailable") + " \xB7 Execution location: " + (state.inventory?.execution_location || "Unavailable")),
    h12("p", null, state.inventory?.status),
    h12("p", { className: "ms-help" }, "Add a tool, learn its documented interface, then confirm one tiny test. No install or generation occurs during discovery."),
    showHelp ? h12("section", { "aria-label": "Detailed tools help" }, h12("h2", null, "Tools, checks and recovery"), h12("p", null, HELP)) : null,
    h12(
      "div",
      { className: "director-grid" },
      h12(
        "aside",
        { "aria-label": "Tool list" },
        !state.cards.some((item) => item.status === "Tested") ? h12("p", null, "No tested tools yet. Add a tool or rescan this profile.") : null,
        ...state.cards.map((item) => h12("button", { key: item.id, type: "button", className: "ms-card", "aria-pressed": item.id === selected, disabled: busy, onClick: () => setSelected(item.id) }, item.name + " \xB7 " + item.status)),
        h12("details", null, h12("summary", null, "Discovered here"), ...(state.inventory?.items || []).map((item, index) => h12(
          "div",
          { key: index },
          h12("p", null, item.name + " \xB7 " + item.kind + " \xB7 " + item.status + " \xB7 " + item.price + " \xB7 " + item.wait),
          button("Learn " + item.name, () => c.learn(item))
        ))),
        h12("details", null, h12("summary", null, "Untested starter templates"), ...state.templates.map((item) => h12("p", { key: item.name }, item.name + " \xB7 Untested")))
      ),
      h12("section", { className: "ms-panel director-detail", "aria-label": "Tool detail" }, card ? h12(
        "div",
        null,
        button("Back to tools", () => setSelected(null)),
        h12("h2", null, card.name),
        h12("p", null, card.status + " \xB7 " + card.operation),
        h12("p", null, card.price + " \xB7 " + card.wait + " \xB7 Evidence date: " + new Date(card.source_date * 1e3).toLocaleDateString()),
        h12("p", null, card.next_action),
        button("Learn this tool", () => c.learn(card)),
        ["Untested", "Needs re-test"].includes(card.status) ? button("Review tiny test", () => setConfirm(card), card.price !== "Zero local call cost") : null,
        button("Disable", () => c.mutate("card.disable", { id: card.id, expected: card.revision })),
        button("Forget binding and notes", () => c.mutate("card.forget", { id: card.id, expected: card.revision })),
        ...card.evidence.map((item, index) => h12(
          "section",
          { key: index },
          h12("p", null, "Tiny test: " + item.elapsed_seconds + " seconds \xB7 " + item.context),
          h12(TakeChecks, { host: c.host, request: item.request, take: {
            id: item.take,
            review: item.user_verdict,
            check: { status: item.check, report: item.report, not_checked: item.not_checked || [] }
          }, onChanged: () => c.open() })
        ))
      ) : h12(
        "form",
        { onSubmit: (event) => {
          event.preventDefault();
          void c.mutate("card.prepare", { name, documentation, help, expected: 0 });
        } },
        h12("h2", null, "Add a tool"),
        h12("label", null, "Tool name", h12("input", { value: name, maxLength: 120, required: true, onChange: (event) => setName(event.target.value) })),
        h12("label", null, "Official documentation URL", h12("input", { type: "url", value: documentation, maxLength: 2e3, onChange: (event) => setDocs(event.target.value) })),
        h12("label", null, "Or paste help / schema from the tool", h12("textarea", { value: help, maxLength: 12e3, onChange: (event) => setHelp(event.target.value) })),
        h12("p", null, "No commands or workflow JSON to write. Do not paste keys, accounts, machine paths or private endpoints."),
        h12("button", { type: "submit", className: "ms-btn", disabled: busy || !name.trim() || !documentation.trim() && !help.trim() }, "Save untested draft")
      ))
    ),
    h12(
      "section",
      { className: "ms-panel", "aria-label": "Recently removed" },
      h12("h2", null, "Recently removed"),
      h12("p", null, "Restore keeps the same take, review, report and original order. Nothing is purged."),
      state.removed.length ? button("Undo last remove", () => {
        const item = state.removed[0];
        void c.mutate("take.restore", { request: item.request, take: item.take, expected: item.revision });
      }) : null,
      state.removed.length ? state.removed.map((item, index) => h12(
        "div",
        { key: item.take },
        h12("span", null, "Removed take " + (index + 1) + " \xB7 Your review: " + item.review + " "),
        button("Restore take " + (index + 1), () => c.mutate("take.restore", { request: item.request, take: item.take, expected: item.revision }))
      )) : h12("p", null, "No removed takes.")
    ),
    confirm ? h12(Confirmation, { key: confirm.id, card: confirm, busy, onCancel: () => setConfirm(null), onConfirm: () => {
      const card2 = confirm;
      setConfirm(null);
      void c.mutate("card.test", { id: card2.id, expected: card2.revision, confirmed: true });
    } }) : null
  ));
}

// studio/native/frontend/entry.js
function Workspace({ createController, createCreation, createProduction, createDirector }) {
  const [lane, setLane] = useState10("creation");
  return createElement(
    "div",
    null,
    createElement(
      "button",
      { onClick: () => setLane(lane === "technical" ? "creation" : "technical") },
      lane === "technical" ? "Back to creations" : "Technical proposals"
    ),
    lane === "technical" ? createElement(TechnicalPage, { createController }) : lane === "tools" ? createElement(DirectorPage, { createController: createDirector, onBack: () => setLane("creation") }) : lane === "production" ? createElement(ProductionPage, { createController: createProduction, onQuickCreate: () => setLane("creation"), onTools: () => setLane("tools") }) : createElement(CreationPage, { createController: createCreation, onProduction: () => setLane("production"), onTools: () => setLane("tools") })
  );
}
var entry_default = {
  id: "motion-studio",
  name: "Motion Studio",
  defaultEnabled: false,
  register(ctx) {
    const controllers = /* @__PURE__ */ new Set();
    const createController = (notify) => {
      const value = new TechnicalController(host, ctx.storage, notify);
      const dispose = value.dispose.bind(value);
      value.dispose = () => {
        dispose();
        controllers.delete(value);
      };
      controllers.add(value);
      return value;
    };
    const createCreation = (notify) => {
      const value = new CreationController(host, notify);
      const dispose = value.dispose.bind(value);
      value.dispose = () => {
        dispose();
        controllers.delete(value);
      };
      controllers.add(value);
      return value;
    };
    const createProduction = (notify) => {
      const value = new ProductionController(host, notify);
      const dispose = value.dispose.bind(value);
      value.dispose = () => {
        dispose();
        controllers.delete(value);
      };
      controllers.add(value);
      return value;
    };
    const createDirector = (notify) => {
      const value = new DirectorController(host, notify);
      const dispose = value.dispose.bind(value);
      value.dispose = () => {
        dispose();
        controllers.delete(value);
      };
      controllers.add(value);
      return value;
    };
    ctx.onDispose(() => {
      for (const controller of controllers) controller.dispose();
      controllers.clear();
    });
    ctx.register({ id: "route", area: ROUTES_AREA, data: { path: "/motion-studio" }, render: () => createElement(Workspace, { createController, createCreation, createProduction, createDirector }) });
    ctx.register({ id: "navigation", area: SIDEBAR_NAV_AREA, data: { path: "/motion-studio", label: "Motion Studio", codicon: "project" } });
  }
};
export {
  entry_default as default
};
