// Tests for apps_script/Code.gs, run with: node --test apps_script/tests/
//
// Code.gs is Apps Script code: it relies on the global SpreadsheetApp /
// Utilities services and has no module exports. Instead of changing the
// production file, each test loads its source into a vm sandbox that stubs
// those services, then drives the real functions.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const CODE_GS = path.join(__dirname, "..", "Code.gs");
const SOURCE = fs.readFileSync(CODE_GS, "utf8");

// ----------------------------- fakes -----------------------------

function columnToNumber(letters) {
  let n = 0;
  for (const ch of letters.toUpperCase()) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n;
}

function parseA1Notation(a1) {
  const m = a1.match(/^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$/i);
  if (!m) throw new Error("not a supported A1 range: " + a1);
  const row = Number(m[2]);
  const col = columnToNumber(m[1]);
  const lastRow = m[4] ? Number(m[4]) : row;
  const lastCol = m[3] ? columnToNumber(m[3]) : col;
  return { row, col, numRows: lastRow - row + 1, numCols: lastCol - col + 1 };
}

// A Sheet stand-in: a sparse cell grid plus a write log, so tests can assert
// both the resulting values and exactly which ranges were touched.
function makeSheet(name, initialRows) {
  const cells = new Map(); // "row,col" -> value
  const writes = [];

  const key = (r, c) => r + "," + c;
  const get = (r, c) => cells.get(key(r, c));

  const sheet = {
    name,
    writes,
    getLastRow() {
      let last = 0;
      for (const k of cells.keys()) {
        const r = Number(k.split(",")[0]);
        if (r > last) last = r;
      }
      return last;
    },
    getMaxRows() {
      return 1000;
    },
    getRange(a, b, c, d) {
      let ref;
      if (typeof a === "string") {
        ref = parseA1Notation(a);
      } else if (c === undefined) {
        ref = { row: a, col: b, numRows: 1, numCols: 1 };
      } else {
        ref = { row: a, col: b, numRows: c, numCols: d };
      }
      return makeRange(ref);
    },
    // Test helpers
    dump() {
      return { cells, get };
    },
  };

  function makeRange(ref) {
    const range = {
      getRow: () => ref.row,
      getColumn: () => ref.col,
      getNumRows: () => ref.numRows,
      getNumColumns: () => ref.numCols,
      getValues() {
        const out = [];
        for (let r = 0; r < ref.numRows; r++) {
          const row = [];
          for (let c = 0; c < ref.numCols; c++) row.push(get(ref.row + r, ref.col + c));
          out.push(row);
        }
        return out;
      },
      setValues(values) {
        values.forEach((row, r) =>
          row.forEach((value, c) => cells.set(key(ref.row + r, ref.col + c), value))
        );
        writes.push({ op: "setValues", ref, values });
        return range;
      },
      setValue(value) {
        cells.set(key(ref.row, ref.col), value);
        writes.push({ op: "setValue", ref, value });
        return range;
      },
      clearContent() {
        for (let r = 0; r < ref.numRows; r++) {
          for (let c = 0; c < ref.numCols; c++) cells.delete(key(ref.row + r, ref.col + c));
        }
        writes.push({ op: "clearContent", ref });
        return range;
      },
      setHorizontalAlignment() {
        return range;
      },
    };
    return range;
  }

  // Seed content, e.g. makeSheet("backend", [["", "", ...], ...]) starting at A1.
  (initialRows || []).forEach((row, r) =>
    row.forEach((value, c) => {
      if (value !== undefined && value !== null) cells.set(key(r + 1, c + 1), value);
    })
  );

  return sheet;
}

function loadSandbox(sheets, options) {
  const opts = options || {};
  const spreadsheet = {
    getSheetByName: (name) => sheets[name] || null,
  };
  const errors = [];
  const sandbox = {
    SpreadsheetApp: { getActiveSpreadsheet: () => spreadsheet },
    Utilities: {
      formatDate: () => opts.now || "15 October, 2026 19:00",
    },
    console: {
      log: () => {},
      error: (msg) => errors.push(String(msg)),
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(SOURCE, sandbox, { filename: CODE_GS });
  sandbox.__spreadsheet = spreadsheet;
  sandbox.__errors = errors;
  return sandbox;
}

// A backend sheet laid out like the formatter writes it: row 1 = headers,
// rows 2+ = data in A..H (Day in column D -> index 3, Time Slot in F -> index 5).
function backendWith(rows) {
  const header = ["Course", "Course Title", "Sect", "Day", "Room", "Time Slot", "Teacher", "Contact"];
  return makeSheet("backend", [header].concat(rows));
}

function dataRow(course, day, timeSlot) {
  return [course, course + " title", "B", day, "120", timeSlot, "SS", "ss@example.com"];
}

// ----------------------------- parseAndFormatTime -----------------------------

test("parseAndFormatTime normalises a portal slot without AM/PM", () => {
  const sandbox = loadSandbox({});
  assert.deepEqual(
    JSON.parse(JSON.stringify(sandbox.parseAndFormatTime("11:45 - 1:0"))),
    { formatted: "11:45 AM - 1:00 PM", sortable: 705 }
  );
});

test("parseAndFormatTime handles a single time", () => {
  const sandbox = loadSandbox({});
  assert.deepEqual(
    JSON.parse(JSON.stringify(sandbox.parseAndFormatTime("9:0"))),
    { formatted: "9:00 AM", sortable: 540 }
  );
});

test("parseAndFormatTime keeps an explicit period", () => {
  const sandbox = loadSandbox({});
  const result = sandbox.parseAndFormatTime("2:30 PM - 4:00 PM");
  assert.equal(result.formatted, "2:30 PM - 4:00 PM");
  assert.equal(result.sortable, 870);
});

test("parseAndFormatTime treats 12:xx as noon", () => {
  const sandbox = loadSandbox({});
  const result = sandbox.parseAndFormatTime("12:0 - 12:50");
  assert.equal(result.formatted, "12:00 PM - 12:50 PM");
  assert.equal(result.sortable, 720);
});

test("parseAndFormatTime treats 12:xx AM as midnight", () => {
  const sandbox = loadSandbox({});
  const result = sandbox.parseAndFormatTime("12:30 AM");
  assert.equal(result.formatted, "12:30 AM");
  assert.equal(result.sortable, 30);
});

test("parseAndFormatTime returns an empty slot for blank input", () => {
  const sandbox = loadSandbox({});
  for (const blank of ["", "   ", null, undefined]) {
    const result = sandbox.parseAndFormatTime(blank);
    assert.equal(result.formatted, "");
    assert.equal(result.sortable, 99999);
  }
});

test("parseAndFormatTime passes unparseable text through, sorting last", () => {
  const sandbox = loadSandbox({});
  const result = sandbox.parseAndFormatTime("TBA");
  assert.equal(result.formatted, "TBA");
  assert.equal(result.sortable, 99998);
});

// ----------------------------- updateMetadata -----------------------------

test("updateMetadata writes the stamp below the data, never inside B..I", () => {
  for (const rowCount of [1, 5, 16, 20, 21, 30, 100]) {
    const target = makeSheet("NewMain", []);
    const sandbox = loadSandbox({ NewMain: target });
    const lastDataRow = 4 + rowCount - 1;

    sandbox.updateMetadata(target, lastDataRow);

    assert.equal(target.writes.length, 2, "stamp + signature");
    const stamp = target.writes[0];
    const signature = target.writes[1];
    assert.equal(stamp.ref.col, 2, "stamp lives in column B");
    assert.equal(signature.ref.col, 2, "signature lives in column B");
    assert.equal(stamp.ref.row, lastDataRow + 2);
    assert.equal(signature.ref.row, lastDataRow + 3);

    for (const write of target.writes) {
      const insideDataBlock =
        write.ref.row >= 4 && write.ref.row <= lastDataRow && write.ref.col <= 9;
      assert.equal(insideDataBlock, false, "stamp must not overlap the B..I data block");
    }
  }
});

test("updateMetadata stamps below the 'no data' notice", () => {
  const target = makeSheet("NewMain", []);
  const sandbox = loadSandbox({ NewMain: target });
  sandbox.updateMetadata(target, 4);
  assert.equal(target.writes[0].ref.row, 6);
  assert.match(target.writes[0].value, /^Last Updated: /);
});

// ----------------------------- sortBackendData -----------------------------

test("sortBackendData sorts by day and time into NewMain", () => {
  const backend = backendWith([
    dataRow("CSE-3201", "Wed", "11:0 - 12:15"),
    dataRow("CSE-3202", "Sat", "9:0 - 10:20"),
    dataRow("CSE-3203", "Wed", "8:30 - 9:50"),
  ]);
  const target = makeSheet("NewMain", []);
  const sandbox = loadSandbox({ backend, NewMain: target });

  sandbox.sortBackendData(null);

  const written = target.writes.find((w) => w.op === "setValues");
  assert.ok(written, "expected data to be written");
  assert.equal(written.ref.row, 4);
  assert.equal(written.ref.col, 2);
  assert.deepEqual(
    written.values.map((row) => [row[0], row[3], row[5]]),
    [
      ["CSE-3202", "Sat", "9:00 AM - 10:20 AM"],
      ["CSE-3203", "Wed", "8:30 AM - 9:50 AM"],
      ["CSE-3201", "Wed", "11:00 AM - 12:15 PM"],
    ]
  );
  assert.equal(written.values[0].length, 8, "only the 8 data columns are written");
});

test("sortBackendData sorts unknown or missing days last", () => {
  const backend = backendWith([
    dataRow("CSE-3201", "", "1:0 - 2:0"),
    dataRow("CSE-3202", "Mon", "9:0 - 10:0"),
    dataRow("CSE-3203", "Funday", "9:0 - 10:0"),
  ]);
  const target = makeSheet("NewMain", []);
  const sandbox = loadSandbox({ backend, NewMain: target });

  sandbox.sortBackendData(null);

  const written = target.writes.find((w) => w.op === "setValues");
  assert.equal(written.values[0][0], "CSE-3202", "a recognised day sorts first");
  assert.deepEqual(
    written.values
      .slice(1)
      .map((row) => row[0])
      .sort(),
    ["CSE-3201", "CSE-3203"],
    "rows with a blank or unrecognised day come last"
  );
});

test("sortBackendData orders ties within a day by start time", () => {
  const backend = backendWith([
    dataRow("CSE-3201", "Sun", "2:0 - 3:0"),
    dataRow("CSE-3202", "Sun", "10:0 - 11:0"),
    dataRow("CSE-3203", "Sun", ""),
  ]);
  const target = makeSheet("NewMain", []);
  const sandbox = loadSandbox({ backend, NewMain: target });

  sandbox.sortBackendData(null);

  const written = target.writes.find((w) => w.op === "setValues");
  assert.deepEqual(
    written.values.map((row) => row[0]),
    ["CSE-3202", "CSE-3201", "CSE-3203"],
    "blank time slots sort after timed ones on the same day"
  );
});

test("sortBackendData clears the previous output before writing", () => {
  const backend = backendWith([dataRow("CSE-3201", "Sun", "9:0 - 10:0")]);
  const target = makeSheet("NewMain", []);
  const sandbox = loadSandbox({ backend, NewMain: target });

  sandbox.sortBackendData(null);

  const ops = target.writes.map((w) => w.op);
  assert.equal(ops[0], "clearContent", "the old output must be cleared first");
  assert.ok(ops.indexOf("setValues") > 0);
});

test("sortBackendData reports the empty-backend case instead of throwing", () => {
  const backend = makeSheet("backend", [["Course", "Course Title"]]); // header only
  const target = makeSheet("NewMain", []);
  const sandbox = loadSandbox({ backend, NewMain: target });

  sandbox.sortBackendData(null);

  const message = target.writes.find((w) => w.op === "setValue");
  assert.match(message.value, /No data found in 'backend' sheet\./);
});

test("sortBackendData logs an error when a sheet is missing", () => {
  const sandbox = loadSandbox({ backend: makeSheet("backend", []) });

  sandbox.sortBackendData(null);

  assert.ok(sandbox.__errors.some((e) => /NewMain/.test(e)));
});

test("triggerSortFromPython delegates to the sort", () => {
  const backend = backendWith([dataRow("CSE-3201", "Sun", "9:0 - 10:0")]);
  const target = makeSheet("NewMain", []);
  const sandbox = loadSandbox({ backend, NewMain: target });

  sandbox.triggerSortFromPython();

  assert.ok(target.writes.some((w) => w.op === "setValues"));
});

test("the onEdit guard ignores edits outside the backend sheet", () => {
  const backend = backendWith([dataRow("CSE-3201", "Sun", "9:0 - 10:0")]);
  const target = makeSheet("NewMain", []);
  const sandbox = loadSandbox({ backend, NewMain: target });

  sandbox.sortBackendData({ source: { getActiveSheet: () => ({ getName: () => "NewMain" }) } });

  assert.equal(target.writes.length, 0);
});
