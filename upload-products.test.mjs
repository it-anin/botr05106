/**
 * เทสฟังก์ชัน pure ของ upload-products.mjs
 * รัน: npm run test:products-upload
 * (import ไฟล์นี้ไม่แตะ Supabase — main() ถูก guard ด้วย isDirectRun)
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

import {
  buildProductRows,
  isStaleFile,
  parseCSV,
  parseFileFlag,
  readCsvText,
  resolveProductCsvColumns,
  shrinkTooMuch,
} from './upload-products.mjs';

const HEADER = 'CF_BARCODE,CF_FMLPRICE,CF_COMMENTS,CF_X,CF_ITEMID,CF_ITEMNAME,CF_UNITNAME,CF_BASEMULTIPLE,CF_ITEMGROUPL1_GROUPNAME';

/** สร้าง CSV เต็มไฟล์จากบรรทัดข้อมูล (คอลัมน์เรียงตาม HEADER ด้านบน) */
function csv(...dataLines) {
  return [HEADER, ...dataLines].join('\r\n');
}

function parseRows(text) {
  const data = parseCSV(text);
  return buildProductRows(data, resolveProductCsvColumns(data[0]));
}

test('readCsvText ตัด UTF-8 BOM ทิ้ง — ไม่งั้นหัวคอลัมน์แรกเป็น \\uFEFFCF_BARCODE แล้ว header check พัง', () => {
  const dir = mkdtempSync(join(tmpdir(), 'r05-'));
  const file = join(dir, 'R05.106.CSV');
  try {
    writeFileSync(file, '﻿' + csv('8851,15,,,100098,Antacil,แผง,1,ยา'), 'utf-8');

    // ยืนยันก่อนว่าไฟล์มี BOM จริง ไม่งั้นเทสนี้ผ่านแบบไม่ได้ทดสอบอะไร
    assert.equal(readFileSync(file, 'utf-8').charCodeAt(0), 0xFEFF);

    const data = parseCSV(readCsvText(file));
    assert.equal(data[0][0], 'CF_BARCODE');
    assert.doesNotThrow(() => resolveProductCsvColumns(data[0]));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('ชื่อสินค้าที่มีขึ้นบรรทัดใหม่ใน quote ไม่ทำให้แถวแตก และเก็บเฉพาะบรรทัดแรก', () => {
  const { rows } = parseRows(csv('8851,15,,,100098,"Antacil\r\nยาลดกรด",แผง,1,ยา'));
  assert.equal(rows.length, 1);
  assert.equal(rows[0].name, 'Antacil');
});

test('escape "" กลายเป็น " และ inch mark กลางฟิลด์ไม่เปิด quote mode', () => {
  const { rows } = parseRows(csv(
    '8851,15,,,100098,"ท่อ ""PVC"" ขาว",เส้น,1,วัสดุ',
    '8852,20,,,100099,ท่อ 2" ขาว,เส้น,1,วัสดุ',
  ));
  assert.equal(rows[0].name, 'ท่อ "PVC" ขาว');
  assert.equal(rows[1].name, 'ท่อ 2" ขาว');
});

test('ขาดหัวคอลัมน์ → throw พร้อมบอกชื่อคอลัมน์ที่หาย', () => {
  const noBarcode = HEADER.replace('CF_BARCODE,', '');
  assert.throws(
    () => resolveProductCsvColumns(noBarcode.split(',')),
    err => {
      assert.match(err.message, /ไม่ใช่รายงาน R05.106/);
      assert.match(err.message, /CF_BARCODE/);
      assert.match(err.message, /ยังไม่ได้แตะข้อมูลเดิม/);
      return true;
    },
  );
});

test('หัวคอลัมน์ตัวพิมพ์เล็ก/มีช่องว่าง/สลับตำแหน่ง ก็ resolve ได้ถูก index', () => {
  const col = resolveProductCsvColumns([
    ' cf_itemname ', 'CF_Barcode', 'CF_ITEMID', 'CF_UNITNAME',
    'CF_FMLPRICE', 'CF_BASEMULTIPLE', 'CF_ITEMGROUPL1_GROUPNAME',
  ]);
  assert.equal(col.name, 0);
  assert.equal(col.barcode, 1);
  assert.equal(col.sku, 2);
});

test('ข้ามแถวที่ไม่มี barcode หรือไม่มี SKU', () => {
  const { rows, stats } = parseRows(csv(
    '8851,15,,,100098,มี barcode และ sku,แผง,1,ยา',
    ',15,,,100099,ไม่มี barcode,แผง,1,ยา',
    '8853,15,,,,ไม่มี sku,แผง,1,ยา',
  ));
  assert.equal(rows.length, 1);
  assert.equal(stats.csvRows, 3);
  assert.equal(stats.skipped, 2);
});

test('แปลงค่า: ราคาว่าง/ไม่ใช่ตัวเลข → 0 · base_multiple ไม่ใช่ตัวเลข → null · หมวดว่าง → ทั่วไป', () => {
  const { rows } = parseRows(csv(
    '8851,,,,100098,ไม่มีราคา,แผง,1,',
    '8852,N/A,,,100099,ราคาเป็นตัวอักษร,แผง,x,ยา',
    '8853,116.50,,,100100,ปกติ,10แผง,10,ยา',
  ));
  assert.equal(rows[0].price, 0);
  assert.equal(rows[0].category, 'ทั่วไป');
  assert.equal(rows[1].price, 0);
  assert.equal(rows[1].base_multiple, null);
  assert.equal(rows[2].price, 116.5);
  assert.equal(rows[2].base_multiple, 10);
});

test('ไม่ยุบแถวซ้ำ — คู่ sku-unit ซ้ำในข้อมูลจริงเป็นของถูกต้อง', () => {
  const { rows } = parseRows(csv(
    '8851,15,,,100098,Antacil,แผง,1,ยา',
    '8851,15,,,100098,Antacil,แผง,1,ยา',
  ));
  assert.equal(rows.length, 2);
});

test('isStaleFile: ไฟล์ของเมื่อวาน = ข้าม · ไฟล์เช้านี้ = อัปโหลด', () => {
  const now = new Date(2026, 8, 3, 8, 30);
  assert.equal(isStaleFile(new Date(2026, 8, 2, 23, 59), now), true);
  assert.equal(isStaleFile(new Date(2026, 8, 3, 0, 0), now), false);
  assert.equal(isStaleFile(new Date(2026, 8, 3, 7, 59), now), false);
});

test('parseFileFlag: รับได้ทั้ง --file <path> และ --file=<path> · ไม่ใส่ path → throw', () => {
  assert.equal(parseFileFlag(['--file', 'C:\\bot\\R05.106.CSV']), 'C:\\bot\\R05.106.CSV');
  assert.equal(parseFileFlag(['--file=C:\\bot\\R05.106.CSV', '--force']), 'C:\\bot\\R05.106.CSV');
  assert.equal(parseFileFlag(['--dry-run']), null);
  assert.equal(parseFileFlag([]), null);
  assert.throws(() => parseFileFlag(['--file']), /ต้องตามด้วย path/);
  assert.throws(() => parseFileFlag(['--file', '--force']), /ต้องตามด้วย path/);
});

test('shrinkTooMuch: หดเกิน 20% เท่านั้นที่หยุด · ตารางว่างอยู่แล้วไม่หยุด', () => {
  assert.equal(shrinkTooMuch(10841, 10800), false);
  assert.equal(shrinkTooMuch(8640, 10800), false);   // หดพอดี 20% — ยังผ่าน (เกณฑ์คือ > 20%)
  assert.equal(shrinkTooMuch(8000, 10800), true);    // หด 26%
  assert.equal(shrinkTooMuch(10, 0), false);
  assert.equal(shrinkTooMuch(10, null), false);
});
