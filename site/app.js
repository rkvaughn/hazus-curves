/**
 * hazus-curves — app.js  (ES module)
 *
 * Query engine: DuckDB-WASM (ESM bundle from jsDelivr) reading Parquet files
 * from data/ via HTTP range requests.
 *
 * Data files expected at ./data/*.parquet (relative to index.html).
 * Deploy step: cp dist/*.parquet site/data/
 *
 * Chart.js is loaded as a classic <script> tag before this module, so
 * window.Chart is available synchronously.
 */

// Use jsDelivr's "+esm" build, not dist/duckdb-browser.mjs. The latter contains a bare
// `import ... from "apache-arrow"`, which a browser cannot resolve without an import
// map, so it fails at load with "Failed to resolve module specifier". The +esm build
// has its dependency specifiers rewritten to absolute URLs.
import * as duckdb from "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/+esm";

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

// Must be an ABSOLUTE URL. DuckDB-WASM's httpfs resolves paths itself and does not
// interpret them relative to the page, so a relative "./data/" fails with "No files
// found that match the pattern".
//
// In production the ~107 MB of Parquet lives in a separate repository, served from its
// own GitHub Pages site. That keeps it out of every clone of the main repository while
// still being CDN-backed and sending both `access-control-allow-origin: *` and Range
// support, which DuckDB-WASM needs to read it cross-origin.
//
// Locally, scripts/serve_site.py syncs the same files into ./data/, so development and
// review do not depend on the network or on the data repo being up to date.
const REMOTE_DATA = "https://rkvaughn.github.io/hazus-curves-data/";
const IS_LOCAL = ["localhost", "127.0.0.1", ""].includes(window.location.hostname);
const DATA_BASE = IS_LOCAL
  ? new URL("data/", window.location.href).href
  : REMOTE_DATA;

// Hurricane attribute keys to surface as individual filter dropdowns.
// All keys are loaded dynamically; this list controls display ordering.
// ─────────────────────────────────────────────────────────────────────────────
// Readable labels for Hazus's terser building-characteristic values.
//
// Every expansion below is quoted or directly derived from the Hazus Hurricane
// Model Technical Manual 7.0 -- none is invented. Most Hazus values are already
// plain ("Wood Truss", "Toe-nail", "Low"/"Medium"/"High") and are left alone.
//
// Roof deck attachment uses a "<nail size> @ <edge>/<field>" shorthand that the
// manual spells out on p. 553: "six penny roof panel nailing at 6-inch spacing on
// the edges and 12-inch spacing in the field ('6d @ 6"/12" roof deck attachment')"
// and "eight penny roof panel nailing at 6-inch spacing on the edges and 6-inch
// spacing in the field ('8d @ 6"/6"')". The other two entries apply that same
// stated grammar.
//
// Keys are "<CharType>|<value>", values exactly as they appear in the data -- note
// Hazus itself is inconsistent about case ('8D @ 6"/6"' in bcName vs '8d' in
// bcDescription), so the key must match the data byte for byte.
const ATTR_VALUE_LABELS = {
  // Roof Deck Attachment -- TM 7.0 p.553
  'Roof Deck Attachment|6d @ 6"/12"':
    'Six-penny nails — 6" edge / 12" field spacing',
  'Roof Deck Attachment|8d @ 6"/12"':
    'Eight-penny nails — 6" edge / 12" field spacing',
  'Roof Deck Attachment|6d/8d Mix @ 6"/6"':
    'Mixed six/eight-penny nails — 6" edge / 6" field spacing',
  'Roof Deck Attachment|8D @ 6"/6"':
    'Eight-penny nails — 6" edge / 6" field spacing',

  // TM 7.0 acronym list: "OWSJ  Open Web Steel Joists"
  "Roof Frame Type|OWSJ": "Open-web steel joist (OWSJ)",

  // TM 7.0: "the South Florida Building Code (SFBC)"
  "Garage, Houses with Shutters|SFBC 1994":
    "South Florida Building Code 1994 (SFBC)",

  // Wind debris exposure source
  "Wind Debris|Res./Comm.": "Residential / commercial",
};

/** Readable label for an attribute value, falling back to the raw value. */
function attrValueLabel(key, value) {
  return ATTR_VALUE_LABELS[`${key}|${value}`] || value;
}

const HU_ATTR_DISPLAY_ORDER = [
  "Roof Shape",
  "Shutters",
  "Roof Deck Attachment",
  "Roof-Wall Connection",
  "Secondary Water Resistance",
  "Roof Cover Type",
  "Roof Cover Quality",
  "Roof Frame Type",
  "Masonry Reinforcing",
  "Wind Debris",
  "Joist Spacing",
  "Truss Spacing",
  "Garage, Houses w/out Shutters",
  "Garage, Houses with Shutters",
  "Number of Units",
  "Tie Downs",
  "Uplift Restraint",
  "Roof Deck Age",
  "Wall Construction",
  "Window Area",
  "Roof Cover Type Hawaii",
  "Roof Deck Attachment Hawaii",
];

// Internal hurricane attribute keys — not exposed as user-facing filters.
const HU_INTERNAL_KEYS = new Set([
  "terrain",
  "geographic_case",
  "terrain_id",
  "surface_roughness_m",
  "wind_building_type_id",
  "characteristic_code",
  "characteristic_unmapped_code",
  "specific_building_type",
]);

// Beyond this many individual curves, force averaging.
const MAX_INDIVIDUAL_CURVES = 20;

// Chart colours (cycles for individual curves).
const PALETTE = [
  "#1a56a0", "#e67e22", "#27ae60", "#8e44ad", "#c0392b",
  "#16a085", "#d35400", "#2980b9", "#f39c12", "#7f8c8d",
];

// ─────────────────────────────────────────────────────────────────────────────
// Global state
// ─────────────────────────────────────────────────────────────────────────────

let conn = null;       // DuckDB connection
let chart = null;      // Chart.js instance
let lastResult = null; // Stored for download

// ─────────────────────────────────────────────────────────────────────────────
// DOM helpers
// ─────────────────────────────────────────────────────────────────────────────

function el(id) { return document.getElementById(id); }

function showLoading(msg) {
  const ld = el("loading");
  ld.style.display = "flex";
  el("loading-msg").textContent = msg || "Loading…";
}

function hideLoading() {
  el("loading").style.display = "none";
}

function showError(msg, detail) {
  const ed = el("error-display");
  ed.style.display = "block";
  el("error-text").textContent = detail ? String(detail) : (msg || "");
  el("status-bar").textContent = msg || "Error";
}

function clearError() {
  el("error-display").style.display = "none";
  el("error-text").textContent = "";
}

function setStatus(msg) {
  el("status-bar").textContent = msg;
}

// ─────────────────────────────────────────────────────────────────────────────
// DuckDB-WASM initialisation
// ─────────────────────────────────────────────────────────────────────────────

async function initDuckDB() {
  const JSDELIVR_BUNDLES = duckdb.getJsDelivrBundles();
  const bundle = await duckdb.selectBundle(JSDELIVR_BUNDLES);

  const workerUrl = URL.createObjectURL(
    new Blob(
      [`importScripts("${bundle.mainWorker}");`],
      { type: "text/javascript" }
    )
  );

  const worker = new Worker(workerUrl);
  const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
  const db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);

  const c = await db.connect();

  // Verify data files are reachable — fail early with a clear message.
  try {
    await c.query(
      `SELECT COUNT(*) FROM read_parquet('${DATA_BASE}curves.parquet')`
    );
  } catch (e) {
    throw new Error(
      `Data files not found at "${DATA_BASE}". ` +
      "Run the deploy step: cp dist/*.parquet site/data/. " +
      "If running locally, serve over HTTP (not file://).  " +
      "Original error: " + e.message
    );
  }

  return c;
}

// ─────────────────────────────────────────────────────────────────────────────
// Arrow result → plain JS array
// ─────────────────────────────────────────────────────────────────────────────

function toRows(arrowResult) {
  // DuckDB-WASM returns Apache Arrow tables; .toArray() gives Row objects.
  return arrowResult.toArray().map(row => {
    const obj = {};
    for (const [k, v] of Object.entries(row.toJSON())) {
      obj[k] = v;
    }
    return obj;
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// SQL helpers
// ─────────────────────────────────────────────────────────────────────────────

function esc(s) {
  // Escape single quotes in SQL string literals.
  return String(s).replace(/'/g, "''");
}

// ─────────────────────────────────────────────────────────────────────────────
// Populate filter dropdowns
// ─────────────────────────────────────────────────────────────────────────────

async function populateFloodFilters() {
  // Occupancy — join with dim_occupancy for descriptions
  const occResult = await conn.query(
    `SELECT o.occupancy, o.description
     FROM read_parquet('${DATA_BASE}dim_occupancy.parquet') o
     WHERE EXISTS (
       SELECT 1 FROM read_parquet('${DATA_BASE}curves.parquet') c
       WHERE c.occupancy = o.occupancy
     )
     ORDER BY o.occupancy`
  );
  const occSel = el("fl-occupancy");
  for (const row of toRows(occResult)) {
    const opt = document.createElement("option");
    opt.value = row.occupancy;
    opt.textContent = row.description
      ? `${row.occupancy} — ${row.description}`
      : row.occupancy;
    occSel.appendChild(opt);
  }

  // Source agency
  const agResult = await conn.query(
    `SELECT DISTINCT source_agency
     FROM read_parquet('${DATA_BASE}curves.parquet')
     WHERE source_agency IS NOT NULL
     ORDER BY source_agency`
  );
  const agSel = el("fl-agency");
  for (const row of toRows(agResult)) {
    const opt = document.createElement("option");
    opt.value = row.source_agency;
    opt.textContent = row.source_agency;
    agSel.appendChild(opt);
  }
}

async function populateHurricaneFilters() {
  // Building types
  const btResult = await conn.query(
    // Names come from dim_building_type, sourced from Table C-1 of the Hazus
    // Hurricane Technical Manual -- the wind workbook itself carries only codes.
    // LEFT JOIN so a code with no sourced description still appears, rather than
    // being dropped or given an invented name.
    `SELECT DISTINCT c.building_type, d.description
     FROM read_parquet('${DATA_BASE}curves_hu.parquet') c
     LEFT JOIN read_parquet('${DATA_BASE}dim_building_type.parquet') d
       ON d.building_type = c.building_type
     WHERE c.building_type IS NOT NULL
     ORDER BY d.description NULLS LAST, c.building_type`
  );
  const btSel = el("hu-building-type");
  for (const row of toRows(btResult)) {
    const opt = document.createElement("option");
    opt.value = row.building_type;
    opt.textContent = row.description
      ? `${row.description} (${row.building_type})`
      : row.building_type;
    btSel.appendChild(opt);
  }

  // Damage types
  const dtResult = await conn.query(
    `SELECT DISTINCT damage_type
     FROM read_parquet('${DATA_BASE}curves_hu.parquet')
     ORDER BY damage_type`
  );
  const dtSel = el("hu-damage-type");
  for (const row of toRows(dtResult)) {
    const opt = document.createElement("option");
    opt.value = row.damage_type;
    opt.textContent = row.damage_type.replace(/_/g, " ");
    dtSel.appendChild(opt);
  }

  // Terrain
  const terrResult = await conn.query(
    `SELECT DISTINCT value
     FROM read_parquet('${DATA_BASE}curve_attributes_hu.parquet')
     WHERE key = 'terrain' AND value IS NOT NULL
     ORDER BY value`
  );
  const terrSel = el("hu-terrain");
  for (const row of toRows(terrResult)) {
    const opt = document.createElement("option");
    opt.value = row.value;
    opt.textContent = row.value;
    terrSel.appendChild(opt);
  }

  // Territory, not raw Hazus case.
  //
  // Hazus's geographic cases are SET-VALUED: "ContUS+Hawaii" means "Used in Continental
  // and Hawaii". Offering the raw cases and matching them with = silently excluded most
  // applicable curves -- picking "Hawaii" returned 14,400 of the 179,820 curves that
  // actually apply there. The selector now offers territories and resolves them to the
  // set of cases covering that territory via dim_geographic_case.
  const geoResult = await conn.query(
    `SELECT territory, count(*) AS n_cases
     FROM read_parquet('${DATA_BASE}dim_geographic_case.parquet')
     GROUP BY territory ORDER BY territory`
  );
  const geoSel = el("hu-geographic-case");
  for (const row of toRows(geoResult)) {
    const opt = document.createElement("option");
    opt.value = row.territory;
    opt.textContent = row.territory;
    geoSel.appendChild(opt);
  }

  // Dynamic attribute filters — load all non-internal keys
  const keyResult = await conn.query(
    `SELECT DISTINCT key
     FROM read_parquet('${DATA_BASE}curve_attributes_hu.parquet')
     WHERE key IS NOT NULL
     ORDER BY key`
  );
  const allKeys = toRows(keyResult)
    .map(r => r.key)
    .filter(k => !HU_INTERNAL_KEYS.has(k));

  // Sort by display order, then alphabetical for remainder
  allKeys.sort((a, b) => {
    const ai = HU_ATTR_DISPLAY_ORDER.indexOf(a);
    const bi = HU_ATTR_DISPLAY_ORDER.indexOf(b);
    if (ai !== -1 && bi !== -1) return ai - bi;
    if (ai !== -1) return -1;
    if (bi !== -1) return 1;
    return a.localeCompare(b);
  });

  const container = el("hu-attr-filters");
  for (const key of allKeys) {
    const valResult = await conn.query(
      `SELECT DISTINCT value
       FROM read_parquet('${DATA_BASE}curve_attributes_hu.parquet')
       WHERE key = '${esc(key)}' AND value IS NOT NULL
       ORDER BY value`
    );
    const values = toRows(valResult).map(r => r.value);
    if (values.length === 0) continue;

    const fieldId = "hu-attr-" + key.replace(/[^a-zA-Z0-9]/g, "_");

    const div = document.createElement("div");
    div.className = "field";

    const lbl = document.createElement("label");
    lbl.setAttribute("for", fieldId);
    lbl.textContent = key;

    const sel = document.createElement("select");
    sel.id = fieldId;
    sel.dataset.attrKey = key;
    sel.className = "hu-attr-select";

    const allOpt = document.createElement("option");
    allOpt.value = "";
    allOpt.textContent = "-- All --";
    sel.appendChild(allOpt);

    for (const v of values) {
      const opt = document.createElement("option");
      opt.value = v;                       // query value stays exactly as stored
      opt.textContent = attrValueLabel(key, v);
      if (opt.textContent !== v) opt.title = `Hazus value: ${v}`;
      sel.appendChild(opt);
    }

    div.appendChild(lbl);
    div.appendChild(sel);
    container.appendChild(div);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Query: Flood
// ─────────────────────────────────────────────────────────────────────────────

async function queryFlood() {
  const occupancy  = el("fl-occupancy").value;
  const damageType = el("fl-damage-type").value;
  const version    = el("fl-version").value;
  const zone       = el("fl-zone").value;
  const agency     = el("fl-agency").value;

  const whereParts = ["c.peril = 'fl'"];
  if (occupancy)  whereParts.push(`c.occupancy = '${esc(occupancy)}'`);
  if (damageType) whereParts.push(`c.damage_type = '${esc(damageType)}'`);
  if (version)    whereParts.push(`c.hazus_version = '${esc(version)}'`);
  if (agency)     whereParts.push(`c.source_agency = '${esc(agency)}'`);

  // Flood zone: filter via assignment_rules (zone is a rule attribute, not on curves directly)
  // Filter on curve_zone_applicability, not assignment_rules.
  //
  // assignment_rules records which curve a building combination selects *by default*.
  // Using it as a zone filter narrowed the library to those defaults -- 101 of 3,046
  // flood curves -- and, because it only held Hazus 6.1 rows, silently returned zero
  // Hazus 4.0 curves for any zone.
  //
  // curve_zone_applicability records which zones Hazus flags a curve as usable in.
  // Note this is still a subset of the library: Hazus publishes zone flags only for
  // the curves it assigns, and the remainder are alternates chosen manually with no
  // zone recorded anywhere. The UI says so rather than implying the filter is complete.
  const zoneJoin = zone
    ? `INNER JOIN (
         SELECT DISTINCT curve_id
         FROM read_parquet('${DATA_BASE}curve_zone_applicability.parquet')
         WHERE flood_zone = '${esc(zone)}'
       ) _ar ON _ar.curve_id = c.curve_id`
    : "";

  const whereClause = "WHERE " + whereParts.join(" AND ");

  // Count matching curves
  const countSql = `
    SELECT COUNT(DISTINCT c.curve_id) AS n
    FROM read_parquet('${DATA_BASE}curves.parquet') c
    ${zoneJoin}
    ${whereClause}`;
  const nCurves = Number(toRows(await conn.query(countSql))[0].n);

  if (nCurves === 0) {
    return { nCurves: 0, curves: [], points: [], averaged: false, meta: floodMeta(occupancy, damageType, version, zone, agency) };
  }

  // Homogeneity check: if no damage_type filter, ensure all matching curves share one type
  if (!damageType) {
    const dtCountSql = `
      SELECT COUNT(DISTINCT c.damage_type) AS n
      FROM read_parquet('${DATA_BASE}curves.parquet') c
      ${zoneJoin}
      ${whereClause}`;
    const dtCount = Number(toRows(await conn.query(dtCountSql))[0].n);
    if (dtCount > 1) {
      return {
        error: "heterogeneous",
        message:
          `The current filters match curves with ${dtCount} different damage types ` +
          "(structure, contents, inventory). Averaging across damage types is not " +
          "meaningful — the y values represent different loss categories. " +
          "Please select a specific damage type.",
      };
    }
  }

  // Fetch points with provenance
  const pointsSql = `
    SELECT cp.curve_id, cp.x, cp.y,
           c.hazus_version, c.source_table, c.source_agency,
           c.damage_type, c.defect_flag, c.occupancy, c.description
    FROM read_parquet('${DATA_BASE}curve_points.parquet') cp
    INNER JOIN read_parquet('${DATA_BASE}curves.parquet') c ON c.curve_id = cp.curve_id
    ${zoneJoin}
    ${whereClause}
    ORDER BY cp.curve_id, cp.x`;
  const points = toRows(await conn.query(pointsSql));

  // Fetch curve metadata
  const curveSql = `
    SELECT c.curve_id, c.hazus_version, c.source_table, c.source_agency,
           c.damage_type, c.defect_flag, c.occupancy, c.description
    FROM read_parquet('${DATA_BASE}curves.parquet') c
    ${zoneJoin}
    ${whereClause}
    ORDER BY c.curve_id`;
  const curves = toRows(await conn.query(curveSql));

  return { nCurves, curves, points, averaged: nCurves > 1, meta: floodMeta(occupancy, damageType, version, zone, agency) };
}

function floodMeta(occupancy, damageType, version, zone, agency) {
  return {
    peril: "fl",
    occupancy: occupancy || null,
    damageType: damageType || null,
    hazusVersion: version || null,
    floodZone: zone || null,
    sourceAgency: agency || null,
    xLabel: "Depth above first finished floor (ft)",
    yLabel: "Damage (% replacement value)",
    xUnits: "ft_above_first_floor",
    yUnits: "percent",
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Query: Hurricane
// ─────────────────────────────────────────────────────────────────────────────

async function queryHurricane() {
  const buildingType = el("hu-building-type").value;
  const damageType   = el("hu-damage-type").value;
  const terrain      = el("hu-terrain").value;
  const geoCase      = el("hu-geographic-case").value;

  const attrSelects = document.querySelectorAll(".hu-attr-select");
  const attrFilters = [];
  for (const sel of attrSelects) {
    if (sel.value) attrFilters.push({ key: sel.dataset.attrKey, value: sel.value });
  }

  const whereParts = ["c.peril = 'hu'"];
  if (buildingType) whereParts.push(`c.building_type = '${esc(buildingType)}'`);
  if (damageType)   whereParts.push(`c.damage_type = '${esc(damageType)}'`);

  // Territory is resolved through dim_geographic_case rather than compared directly.
  // Matching the raw case with = would exclude every curve whose case merely *contains*
  // the territory -- e.g. a "Hawaii" selection would drop all 165,420 ContUS+Hawaii
  // curves, which do apply in Hawaii.
  if (geoCase) {
    whereParts.push(
      `EXISTS (
         SELECT 1 FROM read_parquet('${DATA_BASE}curve_attributes_hu.parquet') _g
         JOIN read_parquet('${DATA_BASE}dim_geographic_case.parquet') _t
           ON _t.case_name = _g.value
         WHERE _g.curve_id = c.curve_id
           AND _g.key = 'geographic_case'
           AND _t.territory = '${esc(geoCase)}'
       )`
    );
  }

  // Attribute conditions (terrain and the dynamic characteristic filters).
  const attrConditions = [];
  if (terrain) attrConditions.push({ key: "terrain", value: terrain });
  for (const af of attrFilters) attrConditions.push(af);

  for (const { key, value } of attrConditions) {
    whereParts.push(
      `EXISTS (
         SELECT 1 FROM read_parquet('${DATA_BASE}curve_attributes_hu.parquet') _a
         WHERE _a.curve_id = c.curve_id
           AND _a.key = '${esc(key)}'
           AND _a.value = '${esc(value)}'
       )`
    );
  }

  const whereClause = "WHERE " + whereParts.join(" AND ");

  // Count
  const countSql = `
    SELECT COUNT(DISTINCT c.curve_id) AS n
    FROM read_parquet('${DATA_BASE}curves_hu.parquet') c
    ${whereClause}`;
  const nCurves = Number(toRows(await conn.query(countSql))[0].n);

  if (nCurves === 0) {
    return { nCurves: 0, curves: [], points: [], averaged: false, meta: hurricaneMeta(buildingType, damageType, terrain, geoCase, attrFilters) };
  }

  // Homogeneity check
  if (!damageType) {
    const dtCountSql = `
      SELECT COUNT(DISTINCT c.damage_type) AS n
      FROM read_parquet('${DATA_BASE}curves_hu.parquet') c
      ${whereClause}`;
    const dtCount = Number(toRows(await conn.query(dtCountSql))[0].n);
    if (dtCount > 1) {
      return {
        error: "heterogeneous",
        message:
          `The current filters match curves with ${dtCount} different damage types. ` +
          "Averaging across damage types is not meaningful — the y values represent " +
          "different loss categories (e.g. building_loss vs content_loss vs debris counts). " +
          "Please select a specific damage type.",
      };
    }
  }

  // Fetch points with provenance
  const pointsSql = `
    SELECT cp.curve_id, cp.x, cp.y,
           c.hazus_version, c.source_table, c.source_agency,
           c.damage_type, c.defect_flag, c.building_type, c.description,
           c.defect_verified
    FROM read_parquet('${DATA_BASE}curve_points_hu.parquet') cp
    INNER JOIN read_parquet('${DATA_BASE}curves_hu.parquet') c ON c.curve_id = cp.curve_id
    ${whereClause}
    ORDER BY cp.curve_id, cp.x`;
  const points = toRows(await conn.query(pointsSql));

  // Fetch curve metadata
  const curveSql = `
    SELECT c.curve_id, c.hazus_version, c.source_table, c.source_agency,
           c.damage_type, c.defect_flag, c.building_type, c.description,
           c.defect_verified
    FROM read_parquet('${DATA_BASE}curves_hu.parquet') c
    ${whereClause}
    ORDER BY c.curve_id`;
  const curves = toRows(await conn.query(curveSql));

  return { nCurves, curves, points, averaged: nCurves > 1, meta: hurricaneMeta(buildingType, damageType, terrain, geoCase, attrFilters) };
}

// The nine hurricane loss classes use THREE different unit systems. Labelling them all
// as "loss ratio" is wrong and actively misleading -- damage_severe is an exceedance
// probability, loss_of_use is measured in days, and the debris classes are lbs/sqft.
// These strings mirror the curve_kind table, which is the authority on units.
const HU_Y_AXIS = {
  damage_slight:        ["Probability of exceeding Slight damage", "probability"],
  damage_moderate:      ["Probability of exceeding Moderate damage", "probability"],
  damage_severe:        ["Probability of exceeding Severe damage", "probability"],
  damage_total:         ["Probability of exceeding Total damage", "probability"],
  building_loss:        ["Building loss (fraction of replacement value)", "fraction"],
  content_loss:         ["Content loss (fraction of content value)", "fraction"],
  loss_of_use:          ["Loss of use (days)", "days"],
  debris_brick_wood:    ["Brick/wood debris (lbs/sq ft)", "lbs_per_sqft"],
  debris_concrete_steel: ["Concrete/steel debris (lbs/sq ft)", "lbs_per_sqft"],
};

function hurricaneMeta(buildingType, damageType, terrain, geoCase, attrFilters) {
  const [yLabel, yUnits] = HU_Y_AXIS[damageType] ||
    ["Value (units vary by damage type — select one, or join curve_kind)", "mixed"];
  return {
    peril: "hu",
    buildingType: buildingType || null,
    damageType: damageType || null,
    terrain: terrain || null,
    geographicCase: geoCase || null,
    attributes: attrFilters,
    xLabel: "3-second peak gust (mph)",
    yLabel,
    xUnits: "mph",
    yUnits,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Averaging
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Unweighted arithmetic mean of y at each x, plus std dev / min / max.
 * NULL y values from the source are preserved as gaps (excluded from stats).
 * Returns { averaged: [{x, y_mean, y_std, y_min, y_max, n_at_x}], curveIds }
 */
function computeAverages(points) {
  const byX = new Map();
  const curveIds = new Set();

  for (const p of points) {
    curveIds.add(p.curve_id);
    if (!byX.has(p.x)) byX.set(p.x, []);
    if (p.y !== null && p.y !== undefined) {
      byX.get(p.x).push(Number(p.y));
    }
  }

  const xs = Array.from(byX.keys()).sort((a, b) => a - b);
  const averaged = xs.map(x => {
    const ys = byX.get(x);
    if (!ys || ys.length === 0) {
      return { x, y_mean: null, y_std: null, y_min: null, y_max: null, n_at_x: 0 };
    }
    const n = ys.length;
    const sum = ys.reduce((a, b) => a + b, 0);
    const mean = sum / n;
    const variance = ys.reduce((acc, v) => acc + (v - mean) ** 2, 0) / n;
    return {
      x,
      y_mean: mean,
      y_std:  Math.sqrt(variance),
      y_min:  Math.min(...ys),
      y_max:  Math.max(...ys),
      n_at_x: n,
    };
  });

  return { averaged, curveIds: Array.from(curveIds) };
}

// ─────────────────────────────────────────────────────────────────────────────
// Chart
// ─────────────────────────────────────────────────────────────────────────────

function destroyChart() {
  if (chart) { chart.destroy(); chart = null; }
}

function renderChart(displayData, meta, nCurves) {
  destroyChart();

  const canvas = el("chart-canvas");
  const placeholder = el("chart-placeholder");
  const wrap = el("chart-wrap");

  canvas.width  = wrap.clientWidth  || 600;
  canvas.height = wrap.clientHeight || 360;
  canvas.style.display = "block";
  placeholder.style.display = "none";

  const ctx = canvas.getContext("2d");
  const Chart = window.Chart; // loaded via classic <script> tag before this module

  const datasets = [];

  if (displayData.averaged) {
    const { averaged, curveIds } = displayData;

    // Mean line
    datasets.push({
      label: `Mean (n = ${curveIds.length} curves, unweighted)`,
      data: averaged.map(p => ({ x: p.x, y: p.y_mean })),
      borderColor: PALETTE[0],
      backgroundColor: "transparent",
      borderWidth: 2,
      pointRadius: 2,
      tension: 0,
      order: 1,
    });

    // Max boundary (fill toward min)
    datasets.push({
      label: "Max",
      data: averaged.map(p => ({ x: p.x, y: p.y_max })),
      borderColor: "rgba(26,86,160,0.30)",
      backgroundColor: "rgba(26,86,160,0.08)",
      borderWidth: 1,
      borderDash: [4, 4],
      pointRadius: 0,
      fill: "+1",   // fill toward next dataset (min line)
      tension: 0,
      order: 2,
    });

    // Min boundary
    datasets.push({
      label: "Min",
      data: averaged.map(p => ({ x: p.x, y: p.y_min })),
      borderColor: "rgba(26,86,160,0.30)",
      backgroundColor: "rgba(26,86,160,0.08)",
      borderWidth: 1,
      borderDash: [4, 4],
      pointRadius: 0,
      fill: false,
      tension: 0,
      order: 3,
    });
  } else {
    // Individual curves
    const byCurve = new Map();
    for (const p of displayData.points) {
      if (!byCurve.has(p.curve_id)) byCurve.set(p.curve_id, []);
      if (p.y !== null && p.y !== undefined) {
        byCurve.get(p.curve_id).push({ x: p.x, y: Number(p.y) });
      }
    }
    let ci = 0;
    for (const [cid, pts] of byCurve) {
      datasets.push({
        label: cid,
        data: pts.sort((a, b) => a.x - b.x),
        borderColor: PALETTE[ci % PALETTE.length],
        backgroundColor: "transparent",
        borderWidth: 1.5,
        pointRadius: 2,
        tension: 0,
      });
      ci++;
    }
  }

  const allX = datasets.flatMap(d => d.data.map(p => p.x)).filter(v => v != null);
  const xMin = allX.length ? Math.min(...allX) : undefined;
  const xMax = allX.length ? Math.max(...allX) : undefined;

  chart = new Chart(ctx, {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: datasets.length <= 12,
          labels: { font: { size: 11 }, boxWidth: 14, padding: 5 },
        },
        tooltip: {
          callbacks: {
            label: item => {
              const v = item.parsed.y;
              const vStr = (v !== null && v !== undefined) ? v.toFixed(4) : "null";
              return `${item.dataset.label}: ${vStr}`;
            },
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          // Pin to the data range. Left to auto-scale, Chart.js pads out to round
          // numbers (-50..50 for a -4..24 ft flood curve) and squashes the plot into
          // a narrow band.
          min: xMin,
          max: xMax,
          title: { display: true, text: meta.xLabel, font: { size: 11 } },
          ticks: { font: { size: 10 } },
        },
        y: {
          title: { display: true, text: meta.yLabel, font: { size: 11 } },
          ticks: { font: { size: 10 } },
          min: 0,
        },
      },
    },
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Stats table
// ─────────────────────────────────────────────────────────────────────────────

function renderStatsTable(averaged) {
  const tbody = el("stats-tbody");
  tbody.innerHTML = "";
  const fmt = v => (v !== null && v !== undefined) ? v.toFixed(4) : "—";

  for (const row of averaged) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${row.x}</td>` +
      `<td>${fmt(row.y_mean)}</td>` +
      `<td>${fmt(row.y_std)}</td>` +
      `<td>${fmt(row.y_min)}</td>` +
      `<td>${fmt(row.y_max)}</td>`;
    tbody.appendChild(tr);
  }
  el("stats-wrap").style.display = "block";
}

// ─────────────────────────────────────────────────────────────────────────────
// Download
// ─────────────────────────────────────────────────────────────────────────────

function downloadBlob(content, filename, type) {
  const blob = new Blob([content], { type });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function buildDownloadRows(result, averageData) {
  if (!result) return [];
  if (averageData) {
    const { averaged, curveIds } = averageData;
    const constituent_ids = curveIds.join("|");
    const first = result.curves && result.curves[0];
    const hasDefect = result.curves && result.curves.some(c => c.defect_flag);
    return averaged.map(p => ({
      curve_id:              "DERIVED",
      label:                 "DERIVED — not a FEMA-published curve",
      constituent_curve_ids: constituent_ids,
      x:                     p.x,
      y_mean:                p.y_mean,
      y_std:                 p.y_std,
      y_min:                 p.y_min,
      y_max:                 p.y_max,
      n_at_x:                p.n_at_x,
      hazus_version:         first ? first.hazus_version : "",
      source_table:          first ? first.source_table : "",
      damage_type:           first ? first.damage_type : "",
      source_agency:         "multiple — see constituent_curve_ids",
      defect_flag:           hasDefect ? "see constituent curves" : "",
    }));
  } else {
    return result.points.map(p => ({
      curve_id:        p.curve_id,
      x:               p.x,
      y:               p.y,
      hazus_version:   p.hazus_version,
      source_table:    p.source_table,
      source_agency:   p.source_agency,
      damage_type:     p.damage_type,
      defect_flag:     p.defect_flag || "",
      defect_verified: p.defect_verified || "",
    }));
  }
}

function rowsToCsv(rows) {
  if (!rows.length) return "";
  const keys = Object.keys(rows[0]);
  const escapeCell = v => {
    const s = (v === null || v === undefined) ? "" : String(v);
    return (s.includes(",") || s.includes('"') || s.includes("\n"))
      ? '"' + s.replace(/"/g, '""') + '"'
      : s;
  };
  return [keys.join(","), ...rows.map(r => keys.map(k => escapeCell(r[k])).join(","))].join("\n");
}

el("dl-csv").addEventListener("click", () => {
  if (!lastResult) return;
  const { result, averageData, meta } = lastResult;
  const rows = buildDownloadRows(result, averageData);
  const ts = new Date().toISOString().slice(0, 19).replace(/[:.]/g, "-");
  downloadBlob(rowsToCsv(rows), `hazus-curves-${meta.peril}-${ts}.csv`, "text/csv");
});

el("dl-json").addEventListener("click", () => {
  if (!lastResult) return;
  const { result, averageData, meta } = lastResult;
  const rows = buildDownloadRows(result, averageData);
  const payload = {
    generated:             new Date().toISOString(),
    note:                  "Not affiliated with or endorsed by FEMA. 'Hazus' is a FEMA trademark.",
    query_meta:            meta,
    n_source_curves:       result.nCurves,
    derived:               !!averageData,
    derived_note:          averageData
      ? "DERIVED — not a FEMA-published curve. Unweighted arithmetic mean of matched curves at each x."
      : null,
    constituent_curve_ids: averageData ? averageData.curveIds : null,
    data:                  rows,
  };
  const ts = new Date().toISOString().slice(0, 19).replace(/[:.]/g, "-");
  downloadBlob(JSON.stringify(payload, null, 2), `hazus-curves-${meta.peril}-${ts}.json`, "application/json");
});

// ─────────────────────────────────────────────────────────────────────────────
// Main query handler
// ─────────────────────────────────────────────────────────────────────────────

let currentPeril = "fl";

async function runQuery() {
  clearError();
  el("defect-banner").style.display = "none";
  el("derived-banner").style.display = "none";
  el("stats-wrap").style.display = "none";
  el("download-row").style.display = "none";
  lastResult = null;

  showLoading("Querying…");
  el("query-btn").disabled = true;

  try {
    const result = currentPeril === "fl" ? await queryFlood() : await queryHurricane();

    if (result.error === "heterogeneous") {
      showError("Cannot average — heterogeneous damage types", result.message);
      destroyChart();
      el("chart-placeholder").textContent = result.message;
      el("chart-placeholder").style.display = "flex";
      el("chart-canvas").style.display = "none";
      return;
    }

    if (result.nCurves === 0) {
      setStatus("No curves match the selected filters.");
      destroyChart();
      el("chart-placeholder").textContent = "No curves match the selected filters.";
      el("chart-placeholder").style.display = "flex";
      el("chart-canvas").style.display = "none";
      return;
    }

    // Defect warnings
    const defectCurves = result.curves.filter(c => c.defect_flag);
    if (defectCurves.length > 0) {
      el("defect-banner").style.display = "block";
      const verified = defectCurves.filter(c => c.defect_verified === "identical_to_1_story");
      el("defect-verified-note").textContent = verified.length > 0
        ? ` ${verified.length} of ${defectCurves.length} flagged curve(s) are verified byte-identical to the 1-story curve.`
        : "";
    }

    // Decide averaging
    let averageData = null;
    let statusMsg;

    if (result.nCurves === 1) {
      statusMsg = `1 curve: ${result.curves[0].curve_id}`;
    } else if (result.nCurves <= MAX_INDIVIDUAL_CURVES) {
      // Multiple but few — average and show individual too? Show averaged for clarity.
      averageData = computeAverages(result.points);
      statusMsg = `${result.nCurves} curves matched — showing unweighted mean ± min/max band.`;
    } else {
      averageData = computeAverages(result.points);
      statusMsg =
        `${result.nCurves} curves matched (max ${MAX_INDIVIDUAL_CURVES} shown individually) — ` +
        `showing unweighted mean ± min/max band.`;
    }

    setStatus(statusMsg);

    // Derived banner
    if (averageData) {
      el("derived-banner").style.display = "block";
      el("derived-detail").textContent =
        ` Unweighted arithmetic mean of ${averageData.curveIds.length} curves at each x. ` +
        `There are no building-stock weights in these data. ` +
        `The shaded band shows the min-to-max range.`;
    }

    // Render
    if (averageData) {
      renderChart({ averaged: averageData.averaged, curveIds: averageData.curveIds }, result.meta, result.nCurves);
      renderStatsTable(averageData.averaged);
    } else {
      renderChart({ points: result.points }, result.meta, result.nCurves);
    }

    lastResult = { result, averageData, meta: result.meta };
    el("download-row").style.display = "flex";

  } catch (err) {
    console.error(err);
    showError("Query failed — see browser console for details", err.message);
  } finally {
    hideLoading();
    el("query-btn").disabled = false;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Peril tab switching
// ─────────────────────────────────────────────────────────────────────────────

function resetResults() {
  destroyChart();
  el("chart-placeholder").textContent = "No data — apply filters and search.";
  el("chart-placeholder").style.display = "flex";
  el("chart-canvas").style.display = "none";
  el("defect-banner").style.display = "none";
  el("derived-banner").style.display = "none";
  el("stats-wrap").style.display = "none";
  el("download-row").style.display = "none";
  clearError();
  setStatus('Select filters and press "Search curves".');
  lastResult = null;
}

// Opening filters. The point is that the page shows a real curve immediately
// instead of an empty chart, so a first-time visitor sees what the tool does
// before working out which of 39 building types to pick.
//
// Chosen because they are the most common cases in the data and each returns a
// small, fast, non-degenerate result: RES1 is the single-family dwelling class
// most flood work starts from, and WSF1 is its hurricane equivalent. Neither
// default is defect-flagged, so nobody is silently handed a known-bad curve.
const DEFAULT_FILTERS = {
  fl: {
    "fl-occupancy": "RES1",
    "fl-damage-type": "structure",
    "fl-version": "6.1",
    "fl-zone": "Riverine",
  },
  hu: {
    "hu-building-type": "WSF1",
    "hu-damage-type": "damage_severe",
    "hu-terrain": "Open",
  },
};

/** Select a value only if the option actually exists, so a data change can't
 *  leave a select silently stuck on a value that no longer matches anything. */
function applyDefaults(peril) {
  let applied = 0;
  for (const [id, value] of Object.entries(DEFAULT_FILTERS[peril] || {})) {
    const sel = document.getElementById(id);
    if (!sel) continue;
    if ([...sel.options].some(o => o.value === value)) {
      sel.value = value;
      applied++;
    } else {
      console.warn(`default ${id}="${value}" not present in the data; left as All`);
    }
  }
  return applied;
}

const autoQueried = { fl: false, hu: false };

function switchPeril(peril) {
  currentPeril = peril;
  el("tab-fl").classList.toggle("active", peril === "fl");
  el("tab-hu").classList.toggle("active", peril === "hu");
  el("flood-filters").classList.toggle("hidden", peril !== "fl");
  el("hurricane-filters").classList.toggle("hidden", peril !== "hu");
  resetResults();

  // Run once per peril on first visit. After that the user is driving, and
  // re-running on every tab switch would throw away their selections.
  if (!autoQueried[peril]) {
    autoQueried[peril] = true;
    applyDefaults(peril);
    runQuery();
  }
}

el("tab-fl").addEventListener("click", () => switchPeril("fl"));
el("tab-hu").addEventListener("click", () => switchPeril("hu"));
el("query-btn").addEventListener("click", runQuery);

// ─────────────────────────────────────────────────────────────────────────────
// Boot
// ─────────────────────────────────────────────────────────────────────────────

async function boot() {
  showLoading("Initialising DuckDB-WASM…");

  try {
    conn = await initDuckDB();
  } catch (err) {
    hideLoading();
    console.error("DuckDB init failed:", err);
    el("init-error").style.display = "block";
    el("init-error-detail").textContent = err.message || String(err);
    document.querySelector("main").style.display = "none";
    return;
  }

  try {
    showLoading("Loading flood filter options…");
    await populateFloodFilters();
    showLoading("Loading hurricane filter options…");
    await populateHurricaneFilters();
  } catch (err) {
    console.error("Filter population failed:", err);
    showError("Failed to load filter options — see console", err.message);
  }

  hideLoading();

  // Land on a real curve rather than an empty chart.
  autoQueried.fl = true;
  applyDefaults("fl");
  await runQuery();
}

boot();
