/**
 * upload-products.mjs
 * อ่านไฟล์ R05.106.CSV แล้วอัปโหลดข้อมูลสินค้าเข้า Supabase (ตาราง products)
 * รันโดย: node upload-products.mjs [--file <path>] [--force] [--dry-run]
 * ปกติไม่เรียกตรง ๆ — tools\run_and_upload.ps1 เรียกให้ต่อท้ายตอนบอท export เสร็จ
 *
 * ⚠️ ไฟล์นี้ต้องมีสำเนาเดียวคือที่นี่ ห้ามก๊อปไปวางโปรเจกต์อื่น เรียกด้วย path เต็มแทน
 *    (.env และ node_modules ถูกหาจากโฟลเดอร์ของ "ไฟล์สคริปต์" ไม่ใช่ cwd ที่เรียก
 *     โปรเจกต์ที่เรียกจึงไม่ต้องมี service key หรือ @supabase/supabase-js ของตัวเอง)
 *
 * 🔗 ต้องซิงค์กับ App.tsx ของ repo it-anin/anin_sale_support (หน้า Admin → Upload R05.106)
 *    ทั้งคู่อ่านไฟล์ R05.106 หัวคอลัมน์ชุดเดียวกันและเขียนตาราง products ตัวเดียวกัน
 *    ถ้า ProMaxx เปลี่ยนหัวคอลัมน์ ต้องแก้ทั้ง 2 ที่ — คนละ repo กันแล้วตั้งแต่ 2569-09-06
 *
 * ต่างจากหน้าเว็บตรงวิธีเขียน:
 *   หน้าเว็บ = delete-all → insert (พังกลางทาง = ตารางว่าง แต่มีคนนั่งดูอยู่)
 *   สคริปต์  = ใส่ products_import ให้ครบ → RPC swap ใน transaction เดียว
 *              (พังตรงไหนข้อมูลเดิมยังอยู่ครบ เพราะรันอัตโนมัติไม่มีใครเฝ้า)
 *
 * exit code: 0 = สำเร็จ · 1 = ผิดพลาด · 2 = ข้าม (ไฟล์ไม่ได้อัปเดตวันนี้)
 */

import { createClient } from '@supabase/supabase-js';
import { readFileSync, existsSync, statSync, appendFileSync } from 'fs';
import { pathToFileURL } from 'url';
import { resolve } from 'path';

// ─── CONFIG ───────────────────────────────────────────────
// ลองไฟล์ CSV จากหลาย path ตามลำดับ — ใช้ path แรกที่เจอ
const CSV_CANDIDATES = [
  'C:\\Users\\AninMainPC\\Desktop\\run-upload-stock\\R05.106.CSV',
  'C:\\Users\\AninMainPC\\Desktop\\run-upload-stock\\R05.106.csv',
  'C:\\Users\\Arm\\Documents\\update_stock\\R05.106.CSV',
  'C:\\Users\\BigYa-spare\\Desktop\\run-upload-stock\\R05.106.CSV',
  'C:\\Users\\BigYa-spare\\Documents\\update_stock\\R05.106.CSV',
];

const SUPABASE_URL = 'https://eogqnedbdpjuptwlqudn.supabase.co';
const CHUNK = 500;
const SHRINK_LIMIT = 0.2;          // ไฟล์เล็กลงเกิน 20% = ผิดปกติ หยุดทันที (เท่าหน้าเว็บ)
const STABILITY_WINDOW_MS = 60_000; // ไฟล์เพิ่งถูกแก้ภายใน 1 นาที = อาจ export ยังไม่เสร็จ
const STABILITY_WAIT_MS = 20_000;
const STABILITY_TRIES = 3;

// service_role key — bypass RLS (ใช้ฝั่ง server เท่านั้น ห้าม commit ลง git)
// อ่านจาก env SUPABASE_SERVICE_KEY ก่อน ถ้าไม่มีลองอ่านจากไฟล์ .env ข้างสคริปต์
function getServiceKey() {
  if (process.env.SUPABASE_SERVICE_KEY) return process.env.SUPABASE_SERVICE_KEY.trim();
  try {
    const envText = readFileSync(new URL('./.env', import.meta.url), 'utf-8');
    const m = envText.match(/^\s*SUPABASE_SERVICE_KEY\s*=\s*(.+)\s*$/m);
    if (m) return m[1].trim();
  } catch { /* ไม่มีไฟล์ .env ก็ข้าม */ }
  return null;
}
// ──────────────────────────────────────────────────────────

// รันตอนไม่มีคนดู — เก็บ log ไว้ย้อนดูว่าเช้าไหนอัปโหลดไม่สำเร็จเพราะอะไร
// (ไม่ redirect ใน .bat เพราะจะทำให้รันมือแล้วไม่เห็น progress บนหน้าจอ)
const LOG_PATH = new URL('./upload-products.log', import.meta.url);
function writeLog(msg) {
  try { appendFileSync(LOG_PATH, `${msg}\n`); } catch { /* เขียน log ไม่ได้ก็ไม่ต้องล้มงาน */ }
}
function log(msg) { console.log(msg); writeLog(msg); }
function logErr(msg) { console.error(msg); writeLog(msg); }

const sleep = ms => new Promise(r => setTimeout(r, ms));

// ── Products CSV (รายงาน R05.106 จาก Promax) ────────────────
// 27 คอลัมน์ ชื่อหัวคอลัมน์นิ่งมาตลอด (ตรวจกับ export จริง 11 ไฟล์ พ.ค.–ส.ค. 2569)
// ⚠️ ค้นคอลัมน์จาก "ชื่อหัว" เท่านั้น ไม่มี fallback ตำแหน่ง — ถ้า fallback ไฟล์ผิดรูปแบบ
//    จะหลุดผ่านแล้วทับ products ทิ้งทั้งตาราง ซึ่งเป็นปัญหาที่ validation นี้มีไว้กัน
// ต้องตรงกับ PRODUCT_CSV_COLUMNS ใน App.tsx เสมอ (2 ทางเขียนตาราง products ตัวเดียวกัน)
const PRODUCT_CSV_COLUMNS = [
  { key: 'barcode',      header: 'CF_BARCODE',               label: 'บาร์โค้ด' },
  { key: 'price',        header: 'CF_FMLPRICE',              label: 'ราคา' },
  { key: 'sku',          header: 'CF_ITEMID',                label: 'SKU' },
  { key: 'name',         header: 'CF_ITEMNAME',              label: 'ชื่อสินค้า' },
  { key: 'unit',         header: 'CF_UNITNAME',              label: 'หน่วย' },
  // คอลัมน์ H — 1 = หน่วยเล็กสุด, >1 = หน่วยใหญ่ (กล่อง = 10 แผง ฯลฯ)
  // เก็บทุกแถว การกรองเหลือ =1 ทำที่ view v_products_by_category (หน้าเลือกตามหมวด)
  { key: 'baseMultiple', header: 'CF_BASEMULTIPLE',          label: 'ตัวคูณหน่วย' },
  // หมวดอยู่คอลัมน์ Q ไม่ใช่ C — C คือ CF_COMMENTS (โน้ตอิสระ ว่าง 99.5% ของแถว)
  { key: 'category',     header: 'CF_ITEMGROUPL1_GROUPNAME', label: 'หมวด' },
];

/**
 * parser เดียวกับ upload-stock.mjs (คัดลอกมาทั้งก้อน ห้ามแก้ตรรกะ)
 * - `"` เปิด quoted mode เฉพาะตอน field === '' → inch mark กลางชื่อ (2") ไม่พัง
 * - ใน quoted mode `\n` ถูกเก็บเป็นตัวอักษร → ชื่อสินค้าที่มีขึ้นบรรทัดใหม่ไม่ทำให้แถวแตก
 * ⚠️ ไม่ตัด UTF-8 BOM ให้ — ผู้เรียกต้อง strip เอง (ต่างจาก PapaParse ที่หน้าเว็บใช้)
 */
export function parseCSV(text) {
  const lines = [];
  let field = '', row = [], inQuote = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuote) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (ch === '"') inQuote = false;
      else field += ch;
    } else {
      if (ch === '"' && field === '') { inQuote = true; }  // เริ่ม quoted field เฉพาะตอนเริ่มฟิลด์
      else if (ch === ',') { row.push(field); field = ''; }
      else if (ch === '\n') { row.push(field); lines.push(row); row = []; field = ''; }
      else if (ch !== '\r') field += ch;
    }
  }
  if (field || row.length) { row.push(field); lines.push(row); }
  return lines;
}

/** อ่านไฟล์ + ตัด BOM — ถ้าไม่ตัด หัวคอลัมน์แรกจะเป็น \uFEFFCF_BARCODE แล้ว header check พังทุกวัน */
export function readCsvText(path) {
  return readFileSync(path, 'utf-8').replace(/^\uFEFF/, '');
}

/** ค้น index ของทุกคอลัมน์ที่ต้องใช้จากแถวหัว — ขาดตัวไหน throw ทันทีก่อนแตะ DB */
export function resolveProductCsvColumns(headerRow) {
  const head = (headerRow ?? []).map(h => String(h ?? '').trim().toUpperCase());
  const idx = {};
  const missing = [];

  for (const col of PRODUCT_CSV_COLUMNS) {
    const i = head.indexOf(col.header);
    if (i < 0) missing.push(`${col.header} (${col.label})`);
    else idx[col.key] = i;
  }

  if (missing.length > 0) {
    const found = head.filter(Boolean).slice(0, 8).join(', ');
    throw new Error(
      `ไฟล์นี้ไม่ใช่รายงาน R05.106\n`
      + `   ไม่พบคอลัมน์: ${missing.join(', ')}\n`
      + `   หัวคอลัมน์ที่เจอ: ${found}${head.filter(Boolean).length > 8 ? ' ...' : ''}\n`
      + `   → ยังไม่ได้แตะข้อมูลเดิม`,
    );
  }
  return idx;
}

/**
 * แปลงแถว CSV → แถวสำหรับ insert (คงพฤติกรรมเดียวกับ handleFileUpload ใน App.tsx ทุกข้อ)
 * ⚠️ ไม่ dedupe — คู่ sku-unit ซ้ำ 80 คู่ในข้อมูลจริงเป็นของถูกต้อง (docs/database.md)
 */
export function buildProductRows(data, col) {
  const rows = [];
  let skipped = 0;
  for (let i = 1; i < data.length; i++) {
    const row = data[i] ?? [];
    const barcode = (row[col.barcode] ?? '').trim();
    const sku = (row[col.sku] ?? '').trim();
    if (!barcode || !sku) { skipped++; continue; }

    const bm = parseFloat(row[col.baseMultiple]);
    rows.push({
      barcode,
      sku,
      name: ((row[col.name] ?? '').trim()).split(/[\r\n]/)[0].trim(),
      unit: (row[col.unit] ?? '').trim(),
      price: parseFloat(row[col.price]) || 0,
      category: (row[col.category] ?? '').trim() || 'ทั่วไป',
      base_multiple: Number.isFinite(bm) ? bm : null,
    });
  }
  return { rows, stats: { csvRows: Math.max(data.length - 1, 0), skipped } };
}

/**
 * อ่าน `--file <path>` หรือ `--file=<path>` จาก argv
 * มีไว้ให้โปรเจกต์อื่น (บอทที่ export R05.106 เอง) ชี้ไฟล์ของตัวเองได้
 * โดยไม่ต้องมาแก้ CSV_CANDIDATES ทุกครั้งที่ย้ายโฟลเดอร์
 */
export function parseFileFlag(argv) {
  const eq = argv.find(a => a.startsWith('--file='));
  if (eq) {
    const path = eq.slice('--file='.length).trim();
    if (!path) throw new Error('--file= ต้องตามด้วย path ของไฟล์ CSV');
    return path;
  }
  const i = argv.indexOf('--file');
  if (i < 0) return null;
  const next = argv[i + 1];
  if (!next || next.startsWith('--')) throw new Error('--file ต้องตามด้วย path ของไฟล์ CSV');
  return next.trim();
}

/** ไฟล์เก่ากว่าเที่ยงคืนของวันนี้ = เช้านี้ export ไม่ออก อย่าอัปโหลดซ้ำของเมื่อวาน */
export function isStaleFile(mtime, now = new Date()) {
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return new Date(mtime).getTime() < midnight.getTime();
}

/** ไฟล์ใหม่หดลงเกิน 20% = export มาไม่ครบ หยุดก่อนทับของเดิม */
export function shrinkTooMuch(newCount, existingCount, limit = SHRINK_LIMIT) {
  if (!existingCount || existingCount <= 0) return false;
  return 1 - newCount / existingCount > limit;
}

/** กัน export ที่วิ่งชนเวลา 08:30 พอดีจนอ่านได้ไฟล์ครึ่งเดียว */
async function waitForStableFile(path) {
  let prev = statSync(path);
  if (Date.now() - prev.mtimeMs >= STABILITY_WINDOW_MS) return prev;

  for (let i = 1; i <= STABILITY_TRIES; i++) {
    log(`   ไฟล์เพิ่งถูกเขียนเมื่อครู่ — รอ ${STABILITY_WAIT_MS / 1000} วิให้ export เสร็จ (${i}/${STABILITY_TRIES})`);
    await sleep(STABILITY_WAIT_MS);
    const next = statSync(path);
    if (next.size === prev.size && next.mtimeMs === prev.mtimeMs) return next;
    prev = next;
  }
  throw new Error('ไฟล์ยังถูกเขียนอยู่ (ขนาดเปลี่ยนตลอด) — ยกเลิก ไม่แตะข้อมูลเดิม');
}

function hintMissingMigration(message) {
  return /products_import|swap_products_from_import/i.test(message)
    ? `${message} — กรุณารัน products-import-swap.sql ใน Supabase ก่อน`
    : message;
}

async function uploadToStaging(supabase, rows) {
  const { error: clearErr } = await supabase.from('products_import').delete().neq('id', 0);
  if (clearErr) throw new Error(hintMissingMigration(`ล้างตารางพักไม่สำเร็จ: ${clearErr.message}`));

  for (let i = 0; i < rows.length; i += CHUNK) {
    const done = Math.min(i + CHUNK, rows.length);
    const { error } = await supabase.from('products_import').insert(rows.slice(i, done));
    if (error) throw new Error(hintMissingMigration(`insert ตารางพักไม่สำเร็จ: ${error.message}`));
    log(`   เขียนตารางพัก ${done.toLocaleString()}/${rows.length.toLocaleString()} รายการ`);
  }
}

function logSummary(stats, rows, existing) {
  const baseUnits = rows.filter(r => r.base_multiple === 1).length;
  log('');
  log('── สรุป ─────────────────────────────');
  log(`   CSV ทั้งหมด          ${stats.csvRows.toLocaleString()} แถว`);
  log(`   ใช้ได้จริง            ${rows.length.toLocaleString()} แถว`);
  log(`   ข้าม (ไม่มี barcode/SKU) ${stats.skipped.toLocaleString()} แถว`);
  log(`   หน่วยเล็กสุด          ${baseUnits.toLocaleString()} รายการ (หน้าเลือกตามหมวดเห็นเท่านี้)`);
  log(`   เดิมใน Supabase       ${(existing ?? 0).toLocaleString()} รายการ`);
}

export async function main(argv = process.argv.slice(2)) {
  const force = argv.includes('--force');
  const dryRun = argv.includes('--dry-run');
  const timestamp = new Date().toLocaleString('th-TH');
  log('');
  log(`[${timestamp}] เริ่มอัปโหลดสินค้า R05.106...`);
  if (force) log('   โหมด: --force (ข้ามการเช็ควันที่ไฟล์ + เช็คไฟล์หด)');
  if (dryRun) log('   โหมด: --dry-run (ตรวจอย่างเดียว ไม่เขียน DB)');

  const supabaseKey = getServiceKey();
  if (!supabaseKey) {
    throw new Error(
      'ไม่พบ SUPABASE_SERVICE_KEY ใน environment หรือไฟล์ .env\n'
      + '   เอา key จาก: Supabase Dashboard → Settings → API → service_role',
    );
  }

  const fileArg = parseFileFlag(argv);
  let csvPath;
  if (fileArg) {
    if (!existsSync(fileArg)) throw new Error(`ไม่พบไฟล์ตามที่ระบุใน --file:\n   ${fileArg}`);
    csvPath = fileArg;
  } else {
    csvPath = CSV_CANDIDATES.find(p => existsSync(p));
    if (!csvPath) {
      throw new Error(`ไม่พบ R05.106.CSV ใน path:\n${CSV_CANDIDATES.map(p => `   - ${p}`).join('\n')}`);
    }
  }
  log(`   ใช้ไฟล์: ${csvPath}${fileArg ? ' (จาก --file)' : ''}`);

  const stat = statSync(csvPath);
  if (isStaleFile(stat.mtime) && !force) {
    log(`⏭️  ข้าม — ไฟล์ไม่ได้ถูกอัปเดตวันนี้ (แก้ไขล่าสุด ${stat.mtime.toLocaleString('th-TH')})`);
    return { skipped: true, uploaded: 0 };
  }
  await waitForStableFile(csvPath);

  const data = parseCSV(readCsvText(csvPath));
  if (data.length < 2) throw new Error('ไฟล์ไม่มีข้อมูล');

  const col = resolveProductCsvColumns(data[0]);
  const { rows, stats } = buildProductRows(data, col);
  if (rows.length === 0) throw new Error('ไม่พบแถวที่มีทั้งบาร์โค้ดและ SKU');

  const supabase = createClient(SUPABASE_URL, supabaseKey);
  const { count: existing, error: countErr } = await supabase
    .from('products')
    .select('id', { count: 'exact', head: true });
  if (countErr) throw new Error(`นับข้อมูลเดิมไม่สำเร็จ: ${countErr.message}`);

  logSummary(stats, rows, existing);

  if (shrinkTooMuch(rows.length, existing) && !force) {
    const pct = Math.round((1 - rows.length / existing) * 100);
    throw new Error(
      `ไฟล์นี้น้อยกว่าข้อมูลเดิม ${pct}% — น่าจะ export มาไม่ครบ ยกเลิกไว้ก่อน\n`
      + '   ถ้าไฟล์ถูกต้องจริงให้รันซ้ำด้วย --force · ยังไม่ได้แตะข้อมูลเดิม',
    );
  }

  if (dryRun) {
    log('');
    log('✅ ตรวจผ่านทั้งหมด (--dry-run ไม่ได้เขียนอะไรลง Supabase)');
    return { skipped: false, uploaded: 0, dryRun: true };
  }

  await uploadToStaging(supabase, rows);

  const { data: swapped, error: swapErr } = await supabase.rpc('swap_products_from_import');
  if (swapErr) throw new Error(hintMissingMigration(`สลับข้อมูลไม่สำเร็จ: ${swapErr.message}`));

  log('');
  log(`✅ อัปโหลดสำเร็จ ${Number(swapped ?? rows.length).toLocaleString()} รายการ`);
  return { skipped: false, uploaded: Number(swapped ?? rows.length) };
}

const isDirectRun = process.argv[1]
  && pathToFileURL(resolve(process.argv[1])).href === import.meta.url;

if (isDirectRun) {
  main()
    .then(result => { if (result.skipped) process.exitCode = 2; })
    .catch(error => {
      logErr(`❌ ${error.message}`);
      process.exitCode = 1;
    });
}
