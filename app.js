"use strict";
(() => {
  // frontend/render.ts
  var CATEGORY_LABELS = {
    image: "Board & schematic images",
    "interactive-bom": "Interactive BOM",
    step: "3D model",
    pdf: "PDF documents",
    gerber: "Gerber",
    drill: "Drill",
    bom: "Bill of materials",
    pnp: "Pick & place",
    netlist: "Netlist",
    archive: "Archives",
    other: "Other files"
  };
  var CATEGORY_ORDER = [
    "image",
    "interactive-bom",
    "step",
    "pdf",
    "gerber",
    "drill",
    "bom",
    "pnp",
    "netlist",
    "archive",
    "other"
  ];
  function resolveCurrentBranch(manifest, requested) {
    const dirs = manifest.branches.map((branch) => branch.dir);
    if (requested && dirs.includes(requested)) return requested;
    if (manifest.defaultBranch && dirs.includes(manifest.defaultBranch)) return manifest.defaultBranch;
    return dirs[0];
  }
  function groupByCategory(files) {
    const byCategory = /* @__PURE__ */ new Map();
    for (const file of files) {
      const bucket = byCategory.get(file.category) ?? [];
      bucket.push(file);
      byCategory.set(file.category, bucket);
    }
    return CATEGORY_ORDER.filter((category) => byCategory.has(category)).map((category) => ({
      category,
      label: CATEGORY_LABELS[category],
      files: byCategory.get(category)
    }));
  }
  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    const units = ["KB", "MB", "GB"];
    let value = bytes / 1024;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024;
      unitIndex += 1;
    }
    return `${value.toFixed(1)} ${units[unitIndex]}`;
  }
  function populateBranchSelect(select, manifest, current) {
    select.replaceChildren();
    if (manifest.branches.length === 0) {
      const option = document.createElement("option");
      option.textContent = "(no branches)";
      option.disabled = true;
      select.append(option);
      select.disabled = true;
      return;
    }
    select.disabled = false;
    for (const branch of manifest.branches) {
      const option = document.createElement("option");
      option.value = branch.dir;
      option.textContent = branch.ref;
      if (branch.dir === current) option.selected = true;
      select.append(option);
    }
  }
  function showMessage(container, message) {
    const paragraph = document.createElement("p");
    paragraph.className = "message";
    paragraph.textContent = message;
    container.replaceChildren(paragraph);
  }
  function renderProjectList(container, projects, branchDir) {
    if (projects.length === 0) {
      showMessage(container, "No projects were built for this branch.");
      return;
    }
    const list = document.createElement("div");
    list.className = "project-list";
    for (const project of projects) {
      const card = document.createElement("a");
      card.className = "project-card";
      card.href = `?branch=${encodeURIComponent(branchDir)}&project=${encodeURIComponent(project.id)}`;
      const title = document.createElement("h2");
      title.textContent = project.name;
      const source = document.createElement("p");
      source.className = "project-source";
      source.textContent = project.source;
      card.append(title, source);
      list.append(card);
    }
    container.replaceChildren(list);
  }
  function renderProjectPage(container, manifest, opts) {
    const fragments = [];
    const header = document.createElement("div");
    header.className = "project-header";
    const back = document.createElement("a");
    back.className = "back-link";
    back.href = `?branch=${encodeURIComponent(opts.branchDir)}`;
    back.textContent = "\u2190 All projects";
    const title = document.createElement("h2");
    title.textContent = manifest.name;
    header.append(back, title);
    if (manifest.generatedAt) {
      const meta = document.createElement("p");
      meta.className = "project-meta";
      meta.textContent = `Generated ${manifest.generatedAt}`;
      header.append(meta);
    }
    if (manifest.zip) {
      const download = document.createElement("a");
      download.className = "download-zip";
      download.href = opts.base + manifest.zip;
      download.textContent = "Download all outputs (.zip)";
      download.setAttribute("download", "");
      header.append(download);
    }
    fragments.push(header);
    for (const group of groupByCategory(manifest.files)) {
      const section = document.createElement("section");
      section.className = `outputs outputs-${group.category}`;
      const heading = document.createElement("h3");
      heading.textContent = group.label;
      section.append(heading);
      for (const file of group.files) {
        section.append(renderOutput(file, opts.base));
      }
      fragments.push(section);
    }
    container.replaceChildren(...fragments);
  }
  function fileLink(file, base) {
    const link = document.createElement("a");
    link.href = base + file.path;
    link.textContent = file.size !== void 0 ? `${file.path} (${formatBytes(file.size)})` : file.path;
    return link;
  }
  function renderOutput(file, base) {
    const url = base + file.path;
    switch (file.category) {
      case "image": {
        const figure = document.createElement("figure");
        const image = document.createElement("img");
        image.loading = "lazy";
        image.src = url;
        image.alt = file.path;
        const caption = document.createElement("figcaption");
        caption.append(fileLink(file, base));
        figure.append(image, caption);
        return figure;
      }
      case "interactive-bom":
      case "pdf": {
        const wrapper = document.createElement("div");
        wrapper.className = "embed";
        const frame = document.createElement("iframe");
        frame.src = url;
        frame.loading = "lazy";
        frame.title = file.path;
        const caption = document.createElement("p");
        caption.append(fileLink(file, base));
        wrapper.append(frame, caption);
        return wrapper;
      }
      case "step": {
        const wrapper = document.createElement("div");
        wrapper.className = "step-viewer";
        wrapper.dataset.model = url;
        const caption = document.createElement("p");
        caption.append(fileLink(file, base));
        wrapper.append(caption);
        return wrapper;
      }
      default: {
        const item = document.createElement("p");
        item.className = "file-item";
        item.append(fileLink(file, base));
        return item;
      }
    }
  }

  // frontend/app.ts
  async function fetchJson(url) {
    try {
      const response = await fetch(url, { cache: "no-cache" });
      if (!response.ok) return void 0;
      return await response.json();
    } catch {
      return void 0;
    }
  }
  function param(name) {
    return new URLSearchParams(window.location.search).get(name);
  }
  var O3DV_URL = "https://cdn.jsdelivr.net/npm/online-3d-viewer@0.18.0/build/engine/o3dv.min.js";
  function loadScript(url) {
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = url;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error(`failed to load ${url}`));
      document.head.append(script);
    });
  }
  async function initStepViewers() {
    const mounts = document.querySelectorAll(".step-viewer[data-model]");
    if (mounts.length === 0) return;
    if (!window.OV) {
      try {
        await loadScript(O3DV_URL);
      } catch {
        return;
      }
    }
    const viewer = window.OV;
    if (!viewer) return;
    for (const mount of mounts) {
      const url = mount.dataset.model;
      if (!url) continue;
      const host = document.createElement("div");
      host.className = "step-canvas";
      mount.prepend(host);
      viewer.Init3DViewerFromUrlList(host, [url], {});
    }
  }
  async function main() {
    const select = document.getElementById("branch-select");
    const content = document.getElementById("content");
    if (!(select instanceof HTMLSelectElement) || !content) return;
    const branches = await fetchJson("branches.json");
    if (!branches) {
      showMessage(content, "No outputs have been published yet.");
      return;
    }
    const current = resolveCurrentBranch(branches, param("branch"));
    populateBranchSelect(select, branches, current);
    select.addEventListener("change", () => {
      window.location.search = `?branch=${encodeURIComponent(select.value)}`;
    });
    if (!current) {
      showMessage(content, "No branches are available.");
      return;
    }
    const projectId = param("project");
    if (projectId) {
      const base = `${current}/${projectId}/`;
      const manifest = await fetchJson(`${base}manifest.json`);
      if (!manifest) {
        showMessage(content, "This project could not be found on this branch.");
        return;
      }
      renderProjectPage(content, manifest, { base, branchDir: current });
      void initStepViewers();
    } else {
      const index = await fetchJson(`${current}/projects.json`);
      if (!index) {
        showMessage(content, "No projects were built for this branch.");
        return;
      }
      renderProjectList(content, index.projects, current);
    }
  }
  void main();
})();
