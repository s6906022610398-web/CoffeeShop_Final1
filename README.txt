COFFEE SHOP MANAGEMENT SYSTEM
==============================

Python 3.10+
Standard Library only

SUBMISSION STRUCTURE
--------------------
CoffeeShop/
    main.py
    README.txt
    data/
        products.dat
        orders.dat
        payments.dat
    reports/
        product_report.txt
        order_report.txt
        payment_report.txt

IMPORTANT:
- มีไฟล์ Python เพียง 1 ไฟล์ คือ main.py
- ไม่ต้อง run program แยกสำหรับแต่ละส่วน
- ทุกการทำงานอยู่ใน Main Menu เดียว
- ข้อมูลหลักเก็บเป็น Binary .dat
- Reports เป็น TXT แยกกัน 3 ไฟล์

MAIN MENU
---------
1. Add
2. Update
3. Delete
4. View
5. Generate Report
0. Exit

REPORTS
-------
1) Product Report
   ใช้ products.dat + orders.dat
   แสดงข้อมูลสินค้า ราคา จำนวนที่ขาย และยอดขาย

2) Order Report
   ใช้ products.dat + orders.dat
   แสดงรายละเอียดคำสั่งซื้อ ชื่อลูกค้า/สินค้า และยอดรวม

3) Payment Report
   ใช้ payments.dat + orders.dat
   แสดงการชำระเงิน และเชื่อมข้อมูล Order/Customer

ทุก Report มี:
- รายละเอียด
- หัวตาราง
- ตารางข้อมูล
- ส่วนสรุปท้ายรายงาน

BINARY DATABASE
---------------
products.dat
    Struct: <i40s20sfiQ
    Record size: 80 bytes

orders.dat
    Struct: <iiiiiiiif20siQ
    Record size: 68 bytes

payments.dat
    Struct: <ii20sf20siQ
    Record size: 68 bytes

ระบบใช้ fixed-length binary records และ logical delete/free-list

การเปลี่ยนข้อมูล
----------------
เมื่อเพิ่ม แก้ไข หรือลบข้อมูลในระบบ แล้วเลือก Generate Report ใหม่
รายงานจะอ่านข้อมูลจาก Binary database ปัจจุบันอีกครั้ง
ดังนั้นรายงานจะเปลี่ยนตามข้อมูลหลัก

วิธีรัน
-------
เปิด Terminal ในโฟลเดอร์นี้ แล้วใช้:

    python main.py

เกณฑ์ตรวจโครงงาน
-----------------
1. มี 3 reports
2. แต่ละ report มีรายละเอียด + หัวตาราง + ตาราง + สรุป
3. แต่ละ report ใช้ข้อมูลจากอย่างน้อย 2 binary files
4. report เป็น TXT แยก 3 ไฟล์
5. ใช้เมนูชุดเดียว
6. แก้ข้อมูลหลักแล้ว report เปลี่ยนตามเมื่อ Generate ใหม่
7. ข้อมูลหลักเก็บแบบ Binary
8. มีไฟล์ .py เพียงไฟล์เดียว


รูปแบบ REPORT (ฉบับแก้ไข)
-------------------------
แต่ละ Report มี "ตารางหลักเพียง 1 ตาราง" ที่รวมข้อมูลจาก Binary files อย่างน้อย 2 ไฟล์เข้าด้วยกัน
ไม่แยกเป็นหลายตารางภายใน Report เดียว

Product Report: products.dat + orders.dat
- เชื่อมด้วย Product ID
- ตารางเดียวแสดง Product, Price, จำนวน Order, Sold Qty และ Sales

Order Report: orders.dat + products.dat
- เชื่อมด้วย Product ID ที่อยู่ใน Order
- ตารางเดียวแสดง Order, Customer, Product/Qty, Product Price และ Order Total

Payment Report: payments.dat + orders.dat
- เชื่อมด้วย Order ID
- ตารางเดียวแสดง Payment, Order, Customer, Method, Paid และ Order Total

ส่วน Summary อยู่ท้ายรายงานและไม่ถือเป็นตารางข้อมูลหลัก

REPORT TABLE RULE
------------------
แต่ละ Report มีตารางข้อมูลหลักเพียง 1 ตารางเท่านั้น ไม่มีตารางย่อย/ตารางที่สอง
โดย Order Report รวมข้อมูล products.dat และ orders.dat ในแถวเดียวกัน

