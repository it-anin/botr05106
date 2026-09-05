-- ============================================================
-- products-import-swap.sql
-- ตารางพัก + RPC สำหรับ upload-products.mjs (อัปโหลด R05.106 อัตโนมัติ 08:30)
-- รันครั้งเดียวใน Supabase SQL Editor ก่อนตั้ง Task Scheduler
--
-- ทำไมต้องมี: หน้าเว็บ (Admin → Upload R05.106) ใช้ delete-all → insert
-- ซึ่งถ้าพังกลางทางตาราง products จะว่าง — ยอมรับได้ตอนมีคนนั่งดูอยู่
-- แต่สคริปต์รัน 08:30 ไม่มีคนเฝ้า จึงเขียนลงตารางพักให้ครบก่อน
-- แล้วค่อยสลับเข้า products ใน transaction เดียว
-- ============================================================

-- ── ตารางพัก ────────────────────────────────────────────────
-- คอลัมน์ตรงกับที่ upload-products.mjs ส่งมา (ไม่มี updated_at — ใส่ตอน swap)
create table if not exists public.products_import (
  id            bigserial primary key,
  barcode       text,
  sku           text,
  name          text,
  unit          text,
  price         numeric,
  category      text,
  base_multiple numeric
);

-- เปิด RLS แต่ไม่สร้าง policy → anon/authenticated แตะไม่ได้เลย
-- สคริปต์ใช้ service_role key ซึ่ง bypass RLS อยู่แล้ว
alter table public.products_import enable row level security;

-- ── RPC สลับข้อมูล ──────────────────────────────────────────
-- ทั้ง function = 1 transaction → พังตรงไหนก็ rollback หมด products ไม่มีทางว่าง
create or replace function public.swap_products_from_import()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare n integer;
begin
  select count(*) into n from public.products_import;

  -- กันเคสเรียก swap ทั้งที่ยังไม่ได้ใส่ข้อมูล (จะกลายเป็นลบ products ทิ้งเปล่าๆ)
  if n = 0 then
    raise exception 'products_import ว่าง — ยกเลิกการสลับข้อมูล';
  end if;

  -- ใช้ delete ไม่ใช่ truncate: truncate จับ ACCESS EXCLUSIVE lock
  -- จะบล็อกคนที่กำลังค้นหาสินค้าอยู่หน้าเว็บ
  --
  -- ⚠️ ต้องมี WHERE เสมอ — Supabase เปิดส่วนขยาย safeupdate ไว้ DELETE ที่ไม่มี WHERE
  -- จะถูกปฏิเสธด้วย 'DELETE requires a WHERE clause' (เจอจริงตอนรันรอบแรก 2569-09-05)
  -- `id is not null` = ทุกแถว เพราะ id เป็น PK (ฝั่งเว็บเลี่ยงปัญหานี้ไปเองเพราะ
  -- PostgREST บังคับให้ใส่ filter อยู่แล้ว เช่น .delete().neq('id', 0))
  delete from public.products where id is not null;

  insert into public.products (barcode, sku, name, unit, price, category, base_multiple, updated_at)
  select barcode, sku, name, unit, price, category, base_multiple, now()
  from public.products_import;

  delete from public.products_import where id is not null;

  return n;
end;
$$;

-- เรียกได้เฉพาะ service_role (สคริปต์ฝั่ง server) ห้าม anon เรียก — เรียกทีเดียวลบทั้งตาราง
revoke all on function public.swap_products_from_import() from public, anon, authenticated;
grant execute on function public.swap_products_from_import() to service_role;
