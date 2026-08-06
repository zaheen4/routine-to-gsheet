// Google Apps Script: Code.gs
// Bound to the target spreadsheet. Reads the raw routine data from the
// 'backend' sheet and writes the sorted, 12-hour-formatted output into
// 'NewMain', stamping a "Last Updated" timestamp.
//
// Deploy this as an API Executable and put the deployment's Script ID in
// your .env as APP_SCRIPT_ID.

const SIGNATURE = "Made by Z  :)";

function triggerSortFromPython() {
  sortBackendData(null);
}

function sortBackendData(e) {
  if (e && e.source.getActiveSheet().getName() !== "backend") return;

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const backendSheet = ss.getSheetByName("backend");
  const targetSheet = ss.getSheetByName("NewMain");
  const targetStartCell = "B4";

  if (!backendSheet || !targetSheet) {
    console.error("Required sheets ('backend' or 'NewMain') not found.");
    return;
  }

  const lastRow = backendSheet.getLastRow();
  if (lastRow < 2) {
    const startRowOutput = targetSheet.getRange(targetStartCell).getRow();
    const startColOutput = targetSheet.getRange(targetStartCell).getColumn();
    targetSheet.getRange(startRowOutput, startColOutput, targetSheet.getMaxRows() - startRowOutput + 1, 8).clearContent();
    targetSheet.getRange(targetStartCell).setValue("No data found in 'backend' sheet.");
    updateMetadata(targetSheet);
    return;
  }

  const data = backendSheet.getRange("A2:H" + lastRow).getValues();
  const dayOrder = { "SAT": 1, "SUN": 2, "MON": 3, "TUE": 4, "WED": 5, "THU": 6, "FRI": 7 };

  const processedData = data.map(row => {
    const day = row[3];
    const timeSlotRaw = row[5];
    let sortableDay = 998;
    if (day && typeof day === 'string' && day.trim() !== '') {
      sortableDay = dayOrder[day.trim().toUpperCase()] || 999;
    }
    const { formatted, sortable } = parseAndFormatTime(timeSlotRaw);
    const newRow = [...row];
    newRow[5] = formatted;
    return [...newRow, sortableDay, sortable];
  });

  processedData.sort((a, b) => {
    const dayDiff = a[a.length - 2] - b[b.length - 2];
    return dayDiff !== 0 ? dayDiff : a[a.length - 1] - b[b.length - 1];
  });

  const startRowOutput = targetSheet.getRange(targetStartCell).getRow();
  const startColOutput = targetSheet.getRange(targetStartCell).getColumn();
  targetSheet.getRange(startRowOutput, startColOutput, Math.max(1, targetSheet.getLastRow() - startRowOutput + 1), 8).clearContent();

  if (processedData.length > 0) {
    targetSheet.getRange(startRowOutput, startColOutput, processedData.length, 8)
      .setValues(processedData.map(row => row.slice(0, 8)));
  }
  updateMetadata(targetSheet);
}

function updateMetadata(sheet) {
  const currentDate = Utilities.formatDate(new Date(), "GMT+6", "d MMMM, yyyy HH:mm");
  sheet.getRange("I24").setValue("Last Updated: " + currentDate).setHorizontalAlignment("left");
  sheet.getRange("I25").setValue(SIGNATURE).setHorizontalAlignment("right");
}

function parseAndFormatTime(timeStr) {
  if (!timeStr || timeStr.trim() === '') return { formatted: "", sortable: 99999 };
  try {
    const parts = timeStr.trim().split(/\s*-\s*/);
    const getSortable = (tStr) => {
      const match = tStr.match(/^(\d{1,2}):(\d{1,2})(?:\s*(AM|PM))?/i);
      if (!match) return { formatted: tStr, sortable: 99998 };
      let hour = parseInt(match[1]);
      const min = parseInt(match[2]);
      const period = match[3] ? match[3].toUpperCase() : (hour >= 7 && hour <= 11 ? 'AM' : 'PM');
      if (period === 'PM' && hour < 12) hour += 12;
      if (period === 'AM' && hour === 12) hour = 0;
      return { 
        formatted: `${hour % 12 || 12}:${min.toString().padStart(2, '0')} ${period}`, 
        sortable: hour * 60 + min 
      };
    };
    const start = getSortable(parts[0]);
    const end = parts[1] ? getSortable(parts[1]) : { formatted: "" };
    return { 
      formatted: end.formatted ? `${start.formatted} - ${end.formatted}` : start.formatted, 
      sortable: start.sortable 
    };
  } catch (e) {
    return { formatted: timeStr, sortable: 99999 };
  }
}
