# บอท Automation สำหรับ ProMaxx Report

บอทกดปุ่มในโปรแกรม `promaxxreport.exe` (SeniorSoft ProMaxx) แบบเขียนสคริปต์เป็นไฟล์ YAML
ออกแบบให้รันอัตโนมัติแบบไม่มีคนเฝ้าได้

## เริ่มใช้งาน

```powershell
# ล็อกอินอัตโนมัติ (งานพื้นฐาน)
python run.py run flows/login.yaml

# ตรวจ flow โดยไม่กดอะไรจริง
python run.py run flows/login.yaml --dry-run

# ดูโครงสร้างหน้าจอปัจจุบัน (ใช้ตอนสร้าง flow ใหม่)
python run.py inspect --launch

# เฝ้าดูและ dump ทุกครั้งที่หน้าจอเปลี่ยน แล้วคลิกด้วยมือทีละขั้น
python run.py inspect --watch

# ดูรายการ action ที่ใช้ได้ใน YAML
python run.py actions

# ปิดโปรแกรม
python run.py stop
```

รหัสผู้ใช้/รหัสผ่านอยู่ในไฟล์ `.env` (ถูก gitignore ไว้) ไม่ได้ฝังในโค้ดหรือไฟล์ flow

## โปรแกรมเป้าหมาย

| หัวข้อ | ค่า |
|---|---|
| ไฟล์ | `C:\SeniorSoft ProMaxx\promaxxreport.exe` |
| working dir | `C:\SeniorSoft ProMaxx` (**จำเป็น** PowerBuilder โหลด `.pbd` จาก cwd) |
| เทคโนโลยี | PowerBuilder 12.5.2 (Sybase), runtime `PBVM125.DLL` |
| window class | `FNWND3125` (หน้าต่างหลัก), `FNWNS3125` (หน้าต่างย่อย/ล็อกอิน) |
| control class | `pbdw125` (DataWindow), `PBTabControl32_100`, `FNUDO3125` |
| กล่องข้อความ | `#32770` (MessageBox มาตรฐานของวินโดวส์) |

## หลักการที่ทำให้บอทรันตอนจอล็อกได้

ทุกคำสั่งส่งผ่าน **window message** ล้วน ไม่มีการขยับเมาส์หรือกดคีย์บอร์ดจริง
จึงไม่ต้องให้หน้าต่างอยู่หน้าสุดและไม่ต้องมีคนอยู่หน้าเครื่อง

| งาน | ใช้ | ไม่ใช้ |
|---|---|---|
| กดปุ่ม | `WM_LBUTTONDOWN/UP` หรือ `BM_CLICK` | `click_input()`, `pyautogui` |
| พิมพ์ | `WM_CHAR` ทีละตัว | `SendInput`, `type_keys()` |
| อ่านข้อความ | `WM_GETTEXT` | `GetWindowText` (อ่านข้าม process ไม่ได้) |
| ถ่ายภาพ | `PrintWindow` | `ImageGrab` (ได้ภาพดำเมื่อจอล็อก) |

## เรื่องที่ต้องรู้เกี่ยวกับ DataWindow

หน้าจอส่วนใหญ่ของ ProMaxx เป็น **DataWindow** (`pbdw125`) ซึ่งวาดทุกอย่างเอง
ช่องกรอก ปุ่ม และตาราง **ไม่ใช่ control จริง** จึงหา handle รายช่องไม่ได้

วิธีที่ใช้ได้ (ยืนยันกับหน้าล็อกอินจริงแล้ว)

1. คลิกด้วย message ลงบนพิกัดของช่องนั้นใน DataWindow
2. PowerBuilder เลื่อน *in-place editor* (control class `Edit` ที่ซ่อนอยู่) มาทับช่องนั้น
3. พิมพ์ค่าลง editor ตัวนั้น แล้วกด `TAB`/`ENTER` เพื่อ commit

**สำคัญ: ต้องใช้ `method: chars` (`WM_CHAR` ทีละตัว) ไม่ใช่ `settext`**
เพราะ `WM_SETTEXT` ไม่แจ้ง DataWindow ว่าค่าเปลี่ยน PowerBuilder จึงไม่ commit
ค่าเข้า column buffer แล้วขึ้นเตือน *"ยังไม่ได้ป้อนข้อมูล User Login"*

หน้าล็อกอิน: DataWindow `control_id=1001`, in-place editor `id=11` (ชื่อผู้ใช้งาน)
และ `id=12` (รหัสผ่าน) — ช่องรหัสผ่านเป็น `ES_PASSWORD` วินโดวส์จึงบล็อกไม่ให้
อ่านค่ากลับข้ามโปรเซส เป็นเหตุผลที่ flow ตั้ง `verify: false` ไว้

## รายการรายงานทางซ้าย (หน้าจอหลัก)

เป็น DataWindow `control_id = 1010` แถวสูง **27 px เท่ากันทุกแถว**
พิกัดในระบบของ DataWindow

```
x = 16             กล่องเครื่องหมาย + / − (ปุ่มขยาย-ยุบ)
x = 80 ขึ้นไป       ตัวข้อความ (ใช้เมื่อจะเลือกแถว ไม่ใช่ขยาย)
y = 8 + 27 × ลำดับแถว     (ลำดับแถวเริ่มนับ 0)
```

ตัวอย่าง `R05.1 รายละเอียดสินค้า` เป็นแถวที่ 10 → `at: { x: 16, y: 278 }`
(ดู `flows/r05_1.yaml`)

**สูตรนี้ใช้ได้เฉพาะตอนที่ยังไม่มีแถวไหนถูกขยายและรายการยังไม่ถูกเลื่อน**
พอขยายแถวใดแล้ว แถวที่อยู่ใต้ลงไปจะเลื่อนหมด ต้องวัดพิกัดใหม่จากภาพหน้าจอ
เนื่องจาก `login.yaml` ใช้ `if_running: restart` ทุกครั้ง flow จึงเริ่มจากสภาพใหม่เสมอ

แถวลูก (รายงานย่อย) มีไอคอนดาวอยู่ที่ **x = 53 — ห้ามคลิก** เพราะเป็นปุ่มตั้ง/ยกเลิก
รายการโปรด ให้คลิกที่ตัวข้อความแทน (x ตั้งแต่ 68 ขึ้นไป ใช้ 150 กำลังดี)
ลำดับแถวลูกของ R05.1 ดูได้ในคอมเมนต์ของ `flows/r05_106.yaml`

## หน้าจอรายงาน (กรอบขวา)

เมื่อคลิกรายงานจากเมนูซ้าย หน้าจอของรายงานจะโผล่ใน **กรอบขวาของหน้าต่างเดิม**
ไม่ได้เปิดหน้าต่างใหม่ ข่าวดีคือของในกรอบนี้เป็น control จริงเกือบทั้งหมด
จึงสั่งงานด้วย locator ได้ตรง ๆ ไม่ต้องใช้พิกัด

| สิ่งที่ต้องการ | locator |
|---|---|
| ชื่อรายงานที่เปิดอยู่ | `{ class_name: "Button", control_id: 1011 }` |
| ปุ่ม สร้างรายงาน / พิมพ์ / เครื่องพิมพ์ / ส่งออก / ซูมพิเศษ | `{ class_name: "Button", title: "สร้างรายงาน" }` ฯลฯ |
| พื้นที่แสดงรายงาน | `{ class_name: "pbdw125", control_id: 1007 }` |
| ช่องซูม (ค่าเริ่มต้น 100) | `pbdw125` id 1006 → `PBEDIT125` id 11 |

ปุ่มแถบเครื่องมือมีตัวซ้ำที่ถูกซ่อนไว้ชื่อเดียวกัน แต่สเปกค้นหาตัดตัวที่มองไม่เห็นออก
อยู่แล้ว (`visible` ค่าเริ่มต้นเป็น true) จึงหาเจอตัวที่ถูกต้องเสมอ

การยืนยันว่าเปิดรายงานถูกตัวควรใช้ `assert_text` กับ Button id 1011 ซึ่งอ่านชื่อรายงาน
จากโปรแกรมโดยตรง แน่นอนกว่าการเทียบภาพ (ดู `flows/r05_106.yaml`)

## ตรวจว่าคลิกโดนจริง (`expect_change`)

PowerBuilder ไม่ตอบอะไรกลับมาเมื่อคลิกพลาด บอทจะเงียบแล้วทำ step ต่อไปทั้งที่
หน้าจอไม่ขยับ ซึ่งอันตรายตอนรันไม่มีคนเฝ้า `dw_click` จึงมีตัวเลือกเทียบภาพก่อน-หลัง

```yaml
- action: dw_click
  datawindow: { class_name: "pbdw125", control_id: 1010 }
  at: { x: 16, y: 278 }
  expect_change: true
  change_region: { top: 305 }     # ตรวจเฉพาะพื้นที่ใต้แถวที่กด
  change_timeout: 5
```

คีย์ทั้งหมดของการตรวจ

| คีย์ | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `expect_change` | `false` | เปิดการตรวจ |
| `change_window` | – | ไปดูการเปลี่ยนแปลงที่หน้าต่างอื่น (ชื่อจาก `as:` หรือสเปก) |
| `change_control` | – | ไปดูที่ control อื่นในหน้าต่างของ step นั้น |
| `change_region` | ทั้งภาพ | `left` / `top` / `right` / `bottom` จำกัดพื้นที่ที่ต้องเปลี่ยน |
| `change_timeout` | `5` | รอนานสุดกี่วินาที |
| `change_min_pixels` | `200` | ต้องเปลี่ยนอย่างน้อยกี่ pixel ถึงจะนับว่าคลิกโดน |

ไม่ใส่ `change_window`/`change_control` = ดูที่ DataWindow ที่คลิกเอง
ใส่เมื่อผลของการคลิกไปโผล่ที่อื่น เช่นคลิกเมนูซ้ายแล้วรายงานโผล่ในกรอบขวา

**พิกัดของ `change_region` นับจากมุมบนซ้ายของกรอบหน้าต่าง** (`GetWindowRect`)
ไม่ใช่ client area — สำหรับ control ลูกที่ไม่มีขอบสองค่านี้เท่ากัน แต่สำหรับ
หน้าต่างหลักจะต่างกันตามความหนาของขอบ

### กับดักที่เจอมาแล้ว 3 อย่าง

1. **คลิกพลาดไปโดนตัวแถว** PowerBuilder จะเลือกแถวนั้น ทำให้ pixel เปลี่ยนเหมือนกัน
   → จำกัดพื้นที่ด้วย `change_region` และ **เว้นอย่างน้อย 1 แถวเต็ม (27 px)
   จากจุดที่คลิก** เพราะวัดจริงแล้วแถบไฮไลต์ลากลงไปถึง `y = จุดคลิก + 16`

2. **ตัวกะพริบ (caret) ในกรอบรายงาน** ทำให้ภาพต่างกันไม่กี่สิบ pixel ตลอดเวลา
   → จึงนับ**จำนวน pixel ที่ต่าง** แทนการเทียบแบบเป๊ะ ค่าเริ่มต้น 200 ห่างจาก
   ของจริงมาก (เปิดรายงานหนึ่งครั้งเปลี่ยนระดับล้าน pixel ส่วนสัญญาณรบกวนราว 130)

3. **ภาพตั้งต้นถูกถ่ายตอนหน้าจอกำลังวาดใหม่** เช่น scrollbar เพิ่งโผล่ทำให้ขนาด
   control เปลี่ยน → บอทถ่ายซ้ำจนได้สองครั้งติดที่เหมือนกันก่อนจะเริ่มคลิก

ถ้าถ่ายภาพไม่ได้หรือได้ภาพสีเดียวล้วน (เช่นตอนจอถูกล็อก) บอทจะ log เตือนแล้ว
ข้ามการตรวจ ไม่ทำให้ flow ล้มผิด ๆ

**ถ้ามีข้อความให้ตรวจได้ ให้ใช้ `assert_text` แทน** — อ่านค่าจากโปรแกรมโดยตรง
แน่นอนกว่าการเทียบภาพทุกกรณี ใช้เทียบภาพเฉพาะตอนที่ไม่มีข้อความให้ยึด

## โครงสร้างไฟล์

```
run.py                  CLI
settings.yaml           ค่าตั้งกลาง (path, timeout, watchdog)
.env                    รหัสผู้ใช้/รหัสผ่าน (gitignored)
flows/login.yaml        flow ล็อกอิน
flows/example_report.yaml  แม่แบบสำหรับ flow ใหม่
bot/win.py              ส่ง/อ่าน window message
bot/locators.py         หาหน้าต่างและ control จากสเปกใน YAML
bot/datawindow.py       จัดการ DataWindow ของ PowerBuilder
bot/actions.py          ทะเบียน action ที่ใช้ใน YAML
bot/runner.py           รัน flow ทีละ step + retry + กันรันซ้อน
bot/watchdog.py         เฝ้า dialog แปลกปลอมที่โผล่ขวาง
bot/inspector.py        dump โครงสร้างหน้าจอ
bot/app.py              เปิด/เกาะ/ปิดโปรแกรม
tools/register_task.ps1 ลงทะเบียน Scheduled Task
logs/  screenshots/     ผลการรัน (gitignored)
```

## เขียน flow ใหม่

```yaml
name: ชื่อ flow
on_error: abort          # หรือ continue
steps:
  - action: run_flow     # ใช้ flow ล็อกอินซ้ำ
    path: flows/login.yaml

  - action: wait_window
    as: main             # ตั้งชื่อไว้ให้ step ถัดไปอ้าง
    window: { class_name: "FNWND3125", title: "Report Seniorsoft ProMaxx" }

  - action: dw_click
    window: main
    datawindow: { class_name: "pbdw125", control_id: 1010 }
    at: { x: 200, y: 20 }
```

ทุก step ใส่เพิ่มได้: `name`, `timeout`, `pause`, `optional: true`,
`retry: { times: 2, delay: 0.5 }`

สเปกหา control รองรับ: `class_name`, `class_name_re`, `title`, `title_re`,
`title_contains`, `control_id`, `index`, `visible`, `enabled`,
`min_width`, `min_height`, `has_child`

เรียงตามความเสถียร: `control_id` > `class_name` + `title` > `class_name` + `index`

## ตั้งรันอัตโนมัติ

```powershell
.\tools\register_task.ps1 -Time 06:30 -Flows "flows/login.yaml"
Start-ScheduledTask -TaskName "ProMaxxReportBot"    # ทดสอบทันที
```

**ข้อจำกัดที่เลี่ยงไม่ได้:** GUI automation ต้องมี interactive desktop
Scheduled Task จึงต้องเป็น *"Run only when user is logged on"* เท่านั้น
(สคริปต์ตั้งค่านี้ให้แล้ว)

สิ่งที่ควรทำเพิ่มบนเครื่องที่จะรันจริง

- ตั้ง **auto-logon** ให้ user นี้ เพื่อให้ session กลับมาเองหลังรีบูต
- `powercfg /change monitor-timeout-ac 0` และปิด screensaver
  (บอททำงานตอนจอล็อกได้ แต่ `PrintWindow` อาจได้ภาพไม่สมบูรณ์ ทำให้ดีบักยาก)
- **ห้ามใช้ Remote Desktop แล้ว disconnect** เพราะเดสก์ท็อปจะถูกทำลาย
  ให้ใช้ session หน้าเครื่องจริง หรือ redirect ด้วย `tscon` ก่อนตัดการเชื่อมต่อ

## เมื่อ flow พัง

บอทเก็บหลักฐานให้อัตโนมัติ

- `logs/bot.log` — log ทุกขั้นตอน (หมุนไฟล์เอง รหัสผ่านถูกแทนด้วย `***`)
- `screenshots/*_ERROR_*.png` — ภาพหน้าจอตอนพัง
- ใน log จะมีโครงสร้าง control ทั้งหมดของหน้าต่างตอนนั้น ให้เทียบกับ locator ใน YAML ได้ทันที

`watchdog` จะคอยจับกล่องข้อความที่โผล่ขวาง แล้วบันทึกภาพ + ข้อความไว้
ตั้งกติกาได้ใน `settings.yaml` (`policy: log` = แค่บันทึก, `dismiss` = กดปิดให้,
`abort` = ให้ flow ล้ม) ค่าเริ่มต้นเป็น `log` เพื่อไม่ให้บอทเผลอกดยืนยันอะไรเอง

ใช้ `abort_if: { class_name: "#32770" }` ใน `wait_window` / `wait_window_gone`
เพื่อให้รู้ผลทันทีเมื่อโปรแกรมขึ้นกล่องเตือน แทนที่จะรอจนหมด timeout

## ข้อจำกัดที่รู้อยู่

- **อ่านค่าในตารางของ DataWindow ไม่ได้** เพราะไม่ใช่ control จริง
  ถ้าต้องการข้อมูล ให้ใช้ปุ่ม Export/Save As ของโปรแกรมแล้วอ่านไฟล์ที่ได้
  (ทางเลือกอื่น: OCR ด้วย Tesseract ที่ `C:\Program Files\Tesseract-OCR`
  หรือ query ฐานข้อมูล Firebird `FBMAXX.FDB` ตรง ๆ)
- โปรแกรมอัปเดตเมื่อไหร่ `control_id` หรือพิกัดอาจเปลี่ยน — แก้ที่ไฟล์ YAML
  ไม่ต้องแตะโค้ด Python รัน `inspect` ใหม่เพื่อดูค่าปัจจุบัน
- ถ้าระบบจำกัด 1 login ต่อ 1 user บอทจะชนกับคนที่ใช้รหัสเดียวกันอยู่
