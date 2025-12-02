# app.py
"""
InvoiceHome-style desktop invoice app (complete, updated)
- Receipts tab now shows ONLY PDFs
- New "My Reports" tab shows parsed JSON metadata in a table (no images)
- Export CSV & open PDF from reports
- Everything else same as previous version (tkcalendar, signature, logo trim, delete ✖, tax percent)
"""
import os
import io
import csv
import json
from datetime import date, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from tkcalendar import DateEntry
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                Spacer, Image as RLImage)
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from PIL import Image, ImageDraw, ImageChops, ImageTk

# PDF styles
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="InvoiceTitle", parent=styles["Title"], alignment=0, fontSize=16, leading=18))
styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontSize=9, leading=11))

# ---------------- utilities ----------------
def ensure_folder(path):
    os.makedirs(path, exist_ok=True)

def currency(v):
    try:
        return f"RM {float(v):,.2f}"
    except Exception:
        return "RM 0.00"

def pil_trim_whitespace(pil, bg_color=(255,255,255)):
    """Trim uniform background/transparent margins from a PIL image and return RGB image."""
    try:
        if pil.mode in ("RGBA", "LA") or (pil.mode == "P" and "transparency" in pil.info):
            bg = Image.new("RGB", pil.size, bg_color)
            try:
                mask = pil.split()[-1] if pil.mode.endswith("A") else None
            except Exception:
                mask = None
            bg.paste(pil, mask=mask)
            rgb = bg
        else:
            rgb = pil.convert("RGB")
        diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, bg_color))
        bbox = diff.getbbox()
        if bbox:
            return rgb.crop(bbox)
        return rgb
    except Exception:
        try:
            return pil.convert("RGB")
        except Exception:
            return pil

def get_rl_image_from_pil(pil, max_width_mm, max_height_mm=None):
    """Convert PIL image to a ReportLab Image flowable sized to fit max mm dims."""
    if not pil:
        return None
    try:
        w_px, h_px = pil.size
        if w_px <= 0 or h_px <= 0:
            return None

        # ensure RGB and flatten alpha
        if pil.mode in ("RGBA", "LA") or (pil.mode == "P" and "transparency" in pil.info):
            bg = Image.new("RGB", pil.size, (255,255,255))
            try:
                mask = pil.split()[-1] if pil.mode.endswith("A") else None
            except Exception:
                mask = None
            bg.paste(pil, mask=mask)
            pil = bg
        elif pil.mode != "RGB":
            pil = pil.convert("RGB")

        raw_dpi = pil.info.get("dpi", None)
        if isinstance(raw_dpi, (tuple, list)) and len(raw_dpi) >= 1:
            dpi = raw_dpi[0]
        else:
            dpi = raw_dpi or 72.0
        try:
            dpi = float(dpi)
            if dpi <= 0:
                dpi = 72.0
        except Exception:
            dpi = 72.0

        w_pts = float(w_px) * 72.0 / dpi
        h_pts = float(h_px) * 72.0 / dpi

        max_w_pts = float(max_width_mm) * mm
        max_h_pts = float(max_height_mm) * mm if max_height_mm else None

        ratio = h_pts / w_pts if w_pts else 1.0
        target_w = w_pts
        target_h = h_pts

        if target_w > max_w_pts:
            target_w = max_w_pts
            target_h = target_w * ratio

        if max_h_pts and target_h > max_h_pts:
            target_h = max_h_pts
            target_w = target_h / ratio

        page_available = A4[0] - (15*mm + 15*mm)
        if target_w > page_available:
            target_w = page_available
            target_h = target_w * ratio

        if target_w <= 0 or target_h <= 0:
            return None

        bio = io.BytesIO()
        pil.save(bio, format="PNG")
        bio.seek(0)
        return RLImage(bio, width=target_w, height=target_h)
    except Exception as ex:
        print("get_rl_image_from_pil failed:", ex)
        return None

# ---------------- PDF generation ----------------
def make_invoice(path, invoice):
    """Build PDF with classic business style and boxed signature."""
    def get_rl_image(src, max_w_mm, max_h_mm=None):
        if not src:
            return None
        if isinstance(src, str):
            try:
                pil = Image.open(src)
            except Exception:
                return None
        else:
            pil = src
        return get_rl_image_from_pil(pil, max_w_mm, max_h_mm)

    doc = SimpleDocTemplate(path, pagesize=A4,
                            rightMargin=15*mm, leftMargin=15*mm,
                            topMargin=20*mm, bottomMargin=20*mm)
    elements = []

    # header logo
    logo_src = invoice.get("logo_image") or invoice.get("logo_path")
    rl_logo = get_rl_image(logo_src, max_w_mm=45, max_h_mm=30)
    if rl_logo:
        elements.append(rl_logo)
        elements.append(Spacer(1, 6))

    # company & address
    elements.append(Paragraph(invoice.get('company_name',''), styles['InvoiceTitle']))
    elements.append(Paragraph(invoice.get('company_address',''), styles['Normal']))
    elements.append(Spacer(1, 8))

    # meta table
    meta_tbl = [
        ['Invoice No:', invoice.get('invoice_number',''), 'Date:', invoice.get('date','')],
        ['Bill To:', invoice.get('bill_to',{}).get('name',''), 'Due Date:', invoice.get('due_date','')],
        ['Contact:', invoice.get('bill_to',{}).get('contact',''), '', '']
    ]
    meta_table = Table(meta_tbl, colWidths=[30*mm, 80*mm, 25*mm, 50*mm])
    meta_table.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('FONTNAME',(0,0),(-1,-1),'Helvetica'),
        ('FONTSIZE',(0,0),(-1,-1),10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 10))

    # items table
    data = [['#', 'Description', 'Qty', 'Unit Price', 'Amount']]
    subtotal = 0.0
    for i, it in enumerate(invoice.get('items', []), start=1):
        try:
            qty = float(it.get('qty', 0))
        except Exception:
            qty = 0.0
        try:
            unit = float(it.get('unit_price', 0.0))
        except Exception:
            unit = 0.0
        amt = round(qty * unit, 2)
        subtotal += amt
        qty_str = str(int(qty)) if float(qty).is_integer() else str(qty)
        data.append([str(i), it.get('desc',''), qty_str, currency(unit), currency(amt)])

    item_table = Table(data, colWidths=[10*mm, 110*mm, 20*mm, 30*mm, 30*mm])
    item_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('ALIGN',(2,1),(-1,-1),'RIGHT'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(item_table)
    elements.append(Spacer(1, 8))

    # totals (tax percent)
    tax_percent = float(invoice.get('tax_rate', 0.0) or 0.0)
    discount = float(invoice.get('discount', 0.0) or 0.0)
    tax = round(subtotal * (tax_percent / 100.0), 2)
    total = round(subtotal + tax - discount, 2)

    totals_tbl = [
        ['', '', 'Subtotal:', currency(subtotal)],
        ['', '', f"Tax ({tax_percent:.0f}%):", currency(tax)],
        ['', '', 'Discount:', currency(discount)],
        ['', '', Paragraph('<b>Total:</b>', styles['Normal']),
              Paragraph(f"<b>{currency(total)}</b>", styles['Normal'])]
    ]
    totals_table = Table(totals_tbl, colWidths=[10*mm, 110*mm, 30*mm, 30*mm], hAlign='RIGHT')
    totals_table.setStyle(TableStyle([
        ('ALIGN',(2,0),(-1,-1),'RIGHT'),
        ('FONTNAME',(2,0),(-1,-1),'Helvetica'),
        ('FONTSIZE',(2,0),(-1,-1),10),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1,12))

    # notes
    if invoice.get('notes'):
        elements.append(Paragraph('<b>Terms and Conditions</b>', styles['Heading4']))
        elements.append(Paragraph(invoice['notes'], styles['Normal']))
        elements.append(Spacer(1,12))

    # signature box
    sig_src = invoice.get("signature_image") or invoice.get("signature_path")
    if sig_src:
        try:
            if isinstance(sig_src, str):
                sig_img = Image.open(sig_src)
            else:
                sig_img = sig_src
            sig_img = sig_img.convert("RGB")
            bg = Image.new("RGB", sig_img.size, (255,255,255))
            diff = ImageChops.difference(sig_img, bg)
            bbox = diff.getbbox()
            if bbox:
                sig_img = sig_img.crop(bbox)

            max_w_px = 800
            wpx, hpx = sig_img.size
            if wpx > max_w_px:
                new_h = int(hpx * (max_w_px / wpx))
                sig_img = sig_img.resize((max_w_px, new_h), Image.LANCZOS)

            bio = io.BytesIO()
            sig_img.save(bio, format="PNG")
            bio.seek(0)

            raw_dpi = sig_img.info.get("dpi", (72,72))[0] if isinstance(sig_img.info.get("dpi", None), (tuple,list)) else sig_img.info.get("dpi", 72)
            try:
                dpi = float(raw_dpi) if raw_dpi and raw_dpi > 0 else 72.0
            except Exception:
                dpi = 72.0
            w_pts = float(sig_img.width) * 72.0 / dpi
            h_pts = float(sig_img.height) * 72.0 / dpi

            box_w = 90 * mm
            box_h = 40 * mm
            ratio = h_pts / w_pts if w_pts else 1.0
            target_w = min(w_pts, box_w)
            target_h = target_w * ratio
            if target_h > box_h:
                target_h = box_h
                target_w = target_h / ratio

            page_available = A4[0] - (15*mm + 15*mm)
            if target_w > page_available:
                target_w = page_available
                target_h = target_w * ratio

            bio.seek(0)
            sig_rl = RLImage(bio, width=target_w, height=target_h)

            signature_table = Table(
                [[Paragraph("<b>Authorized Signature</b>", styles["Normal"])],
                 [sig_rl]],
                colWidths=[box_w]
            )
            signature_table.setStyle(TableStyle([
                ('BOX', (0,0), (-1,-1), 0.8, colors.black),
                ('ALIGN', (0,1), (0,1), 'CENTER'),
                ('VALIGN', (0,1), (0,1), 'BOTTOM'),
                ('TOPPADDING', (0,1), (0,1), 6),
                ('BOTTOMPADDING', (0,1), (0,1), 6),
                ('ALIGN', (0,0), (0,0), 'CENTER'),
            ]))
            elements.append(Spacer(1, 12))
            elements.append(signature_table)
        except Exception as ex:
            print("Signature embedding failed:", ex)

    try:
        doc.build(elements)
    except Exception as e:
        print("PDF build failed:", e)
        raise

# ---------------- GUI Application ----------------
class InvoiceApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("InvoiceHome — Classic (Minimal UI)")
        self.geometry("1180x760")
        self.minsize(960, 620)

        # model
        self.items = []
        self.logo_path = None
        self.logo_in_memory = None
        self.logo_thumbnail = None
        self.signature_image = None
        self.signature_thumbnail = None

        self.invoices_folder = os.path.join(os.getcwd(), "invoices")
        ensure_folder(self.invoices_folder)

        # UI
        self._setup_style()
        self._create_menu()
        self.create_widgets()
        self.load_receipts_list()
        self.load_reports_table()
        self.set_next_invoice_number()
        self.update_totals()

    def _setup_style(self):
        s = ttk.Style(self)
        try:
            s.theme_use('clam')
        except Exception:
            pass
        s.configure("Header.TLabel", font=("Helvetica", 13, "bold"))
        s.configure("Accent.TButton", foreground="white", background="#0a84ff")
        s.map("Accent.TButton", background=[('active', '#0666cc')])

    def _create_menu(self):
        menubar = tk.Menu(self)
        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="New Invoice", command=self.reset_form, accelerator="Ctrl+N")
        filem.add_separator()
        filem.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="File", menu=filem)
        self.config(menu=menubar)
        self.bind_all("<Control-n>", lambda e: self.reset_form())

    def create_widgets(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        # Invoice tab
        inv_tab = ttk.Frame(notebook)
        notebook.add(inv_tab, text="Invoice")

        main = ttk.Frame(inv_tab, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(main)
        top.pack(fill=tk.X, pady=(0,8))

        left_top = ttk.Frame(top)
        left_top.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(left_top, text="From", style="Header.TLabel").pack(anchor=tk.W)
        self.from_txt = tk.Text(left_top, height=5, wrap=tk.WORD)
        self.from_txt.pack(fill=tk.X, pady=4)
        self.from_txt.insert("1.0", "Your Company Name\nAddress line 1\nAddress line 2")

        ttk.Label(left_top, text="Bill To", style="Header.TLabel").pack(anchor=tk.W, pady=(6,0))
        self.bill_txt = tk.Text(left_top, height=4, wrap=tk.WORD)
        self.bill_txt.pack(fill=tk.X, pady=4)
        self.bill_txt.insert("1.0", "Customer Name")

        right_top = ttk.Frame(top, width=360)
        right_top.pack(side=tk.RIGHT, fill=tk.Y, padx=(8,0))
        right_top.pack_propagate(False)

        logo_frame = ttk.Frame(right_top, relief=tk.RIDGE, padding=8)
        logo_frame.pack(fill=tk.X)
        ttk.Label(logo_frame, text="Logo", font=("Helvetica", 10, "bold")).pack()
        logo_frame.config(height=120)
        logo_frame.pack_propagate(False)

        btn_row = ttk.Frame(logo_frame)
        btn_row.pack(fill=tk.X, pady=6)
        ttk.Button(btn_row, text="Select Logo", command=self.choose_logo).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Clear", command=self.clear_logo).pack(side=tk.LEFT, padx=6)

        # fixed canvas for logo preview
        self.logo_canvas = tk.Canvas(logo_frame, width=140, height=80, bg="#ffffff", highlightthickness=0)
        self.logo_canvas.pack(pady=(6,0))
        try:
            self.logo_canvas.create_text(70, 40, text="No logo", fill="#777")
        except Exception:
            pass

        # meta inputs
        meta_frame = ttk.Frame(right_top, padding=(0,8))
        meta_frame.pack(fill=tk.X, pady=6)

        ttk.Label(meta_frame, text="Invoice #").grid(row=0, column=0, sticky=tk.W)
        self.inv_ent = ttk.Entry(meta_frame, width=20)
        self.inv_ent.grid(row=0, column=1, padx=6, sticky=tk.W)

        ttk.Label(meta_frame, text="Invoice Date").grid(row=1, column=0, sticky=tk.W)
        self.date_ent = DateEntry(meta_frame, width=18, date_pattern='yyyy-mm-dd')
        self.date_ent.grid(row=1, column=1, padx=6, sticky=tk.W)
        self.date_ent.set_date(date.today())

        ttk.Label(meta_frame, text="Due Date").grid(row=2, column=0, sticky=tk.W)
        self.due_ent = DateEntry(meta_frame, width=18, date_pattern='yyyy-mm-dd')
        self.due_ent.grid(row=2, column=1, padx=6, sticky=tk.W)
        self.due_ent.set_date(date.today() + timedelta(days=15))

        ttk.Label(meta_frame, text="Contact").grid(row=3, column=0, sticky=tk.W)
        self.contact_ent = ttk.Entry(meta_frame, width=20)
        self.contact_ent.grid(row=3, column=1, padx=6, sticky=tk.W)

        # Items area
        items_frame = ttk.LabelFrame(main, text="Description / Amount", padding=8)
        items_frame.pack(fill=tk.BOTH, expand=True)

        toolbar = ttk.Frame(items_frame)
        toolbar.pack(fill=tk.X, pady=(0,6))
        ttk.Button(toolbar, text="+ Add New Item", command=self.open_add_item).pack(side=tk.LEFT)

        # Tree with delete column (✖)
        self.tree = ttk.Treeview(items_frame, columns=("del","desc","qty","unit","amt"), show="headings", selectmode="browse")
        self.tree.heading("del", text="")  # delete glyph column
        self.tree.column("del", width=30, anchor=tk.CENTER, stretch=False)
        self.tree.heading("desc", text="Description"); self.tree.heading("qty", text="Qty")
        self.tree.heading("unit", text="Unit Price"); self.tree.heading("amt", text="Amount")
        self.tree.column("desc", width=540); self.tree.column("qty", width=80, anchor=tk.E)
        self.tree.column("unit", width=120, anchor=tk.E); self.tree.column("amt", width=120, anchor=tk.E)
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        # bind clicks for delete column & keyboard delete
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<Delete>", lambda e: self.remove_selected_item())

        right_tot = ttk.Frame(items_frame, width=300)
        right_tot.pack(side=tk.RIGHT, fill=tk.Y, padx=(8,0))
        right_tot.pack_propagate(False)

        ttk.Label(right_tot, text="Subtotal", font=("Helvetica", 10)).pack(anchor=tk.E, pady=(10,0), padx=6)
        self.subtotal_var = tk.StringVar(value="RM 0.00")
        ttk.Label(right_tot, textvariable=self.subtotal_var, font=("Helvetica", 10)).pack(anchor=tk.E, padx=6)
        ttk.Label(right_tot, text="Tax (%)", font=("Helvetica", 10)).pack(anchor=tk.E, pady=(8,0), padx=6)
        self.tax_ent = ttk.Entry(right_tot, width=10); self.tax_ent.pack(anchor=tk.E, padx=6); self.tax_ent.insert(0, "0.00")
        ttk.Label(right_tot, text="Discount", font=("Helvetica", 10)).pack(anchor=tk.E, pady=(8,0), padx=6)
        self.disc_ent = ttk.Entry(right_tot, width=10); self.disc_ent.pack(anchor=tk.E, padx=6); self.disc_ent.insert(0, "0.00")
        ttk.Separator(right_tot, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Label(right_tot, text="TOTAL", font=("Helvetica", 12, "bold")).pack(anchor=tk.E)
        self.total_var = tk.StringVar(value="RM 0.00")
        ttk.Label(right_tot, textvariable=self.total_var, font=("Helvetica", 14, "bold")).pack(anchor=tk.E, padx=6)

        # live update bindings for tax/discount
        self.tax_ent.bind("<KeyRelease>", lambda e: self.update_totals())
        self.tax_ent.bind("<FocusOut>", lambda e: self.update_totals())
        self.disc_ent.bind("<KeyRelease>", lambda e: self.update_totals())
        self.disc_ent.bind("<FocusOut>", lambda e: self.update_totals())

        # bottom: terms + signature
        bottom = ttk.Frame(main, padding=(0,8))
        bottom.pack(fill=tk.X)

        left_bot = ttk.Frame(bottom)
        left_bot.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(left_bot, text="Terms and Conditions", font=("Helvetica", 10, "bold")).pack(anchor=tk.W)
        self.terms_txt = tk.Text(left_bot, height=4)
        self.terms_txt.pack(fill=tk.BOTH, expand=True, pady=4)
        self.terms_txt.insert("1.0", "Payment is due within 15 days")

        right_bot = ttk.Frame(bottom, width=340)
        right_bot.pack(side=tk.RIGHT, fill=tk.Y, padx=(8,0))
        right_bot.pack_propagate(False)
        sig_frame = ttk.Frame(right_bot, relief=tk.RIDGE, padding=8)
        sig_frame.pack(fill=tk.X)
        ttk.Label(sig_frame, text="Signature", font=("Helvetica", 10, "bold")).pack()
        ttk.Button(sig_frame, text="✍ Sign here", command=self.open_signature).pack(pady=6)
        ttk.Button(sig_frame, text="Clear", command=self.clear_signature).pack()
        self.sig_preview_label = ttk.Label(sig_frame, text="No signature")
        self.sig_preview_label.pack(pady=(6,0))

        save_frame = ttk.Frame(self)
        save_frame.pack(fill=tk.X, pady=(10,8), padx=8)
        ttk.Button(save_frame, text="💾 Save Invoice", command=self.save_invoice_fullwidth, style="Accent.TButton").pack(fill=tk.X)

        # Receipts tab (PDFs only)
        receipts_tab = ttk.Frame(notebook)
        notebook.add(receipts_tab, text="Receipts")

        rtop = ttk.Frame(receipts_tab, padding=8)
        rtop.pack(fill=tk.X)
        ttk.Label(rtop, text="Saved PDFs", font=("Helvetica", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(rtop, text="Refresh", command=self.load_receipts_list).pack(side=tk.RIGHT)
        ttk.Button(rtop, text="Open Selected", command=self.open_selected_receipt).pack(side=tk.RIGHT, padx=6)
        ttk.Button(rtop, text="Delete Selected", command=self.delete_selected_receipt).pack(side=tk.RIGHT)

        self.receipts_listbox = tk.Listbox(receipts_tab)
        self.receipts_listbox.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        # Reports tab (JSON metadata)
        reports_tab = ttk.Frame(notebook)
        notebook.add(reports_tab, text="My Reports")

        rtop2 = ttk.Frame(reports_tab, padding=8)
        rtop2.pack(fill=tk.X)
        ttk.Label(rtop2, text="Invoice Reports", font=("Helvetica", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(rtop2, text="Refresh", command=self.load_reports_table).pack(side=tk.RIGHT)
        ttk.Button(rtop2, text="Export CSV", command=self.export_reports_csv).pack(side=tk.RIGHT, padx=6)
        ttk.Button(rtop2, text="Open PDF", command=self.open_pdf_from_report).pack(side=tk.RIGHT, padx=6)

        # reports treeview
        cols = ("customer","invoice","date","due_date","contact","tax_pct","discount","subtotal","tax_amt","total")
        self.reports_tree = ttk.Treeview(reports_tab, columns=cols, show="headings", selectmode="browse")
        headings = {
            "customer":"Customer",
            "invoice":"Invoice No",
            "date":"Date",
            "due_date":"Due Date",
            "contact":"Contact",
            "tax_pct":"Tax %",
            "discount":"Discount",
            "subtotal":"Subtotal",
            "tax_amt":"Tax Amt",
            "total":"Total"
        }
        for c in cols:
            self.reports_tree.heading(c, text=headings[c])
            if c == "customer":
                self.reports_tree.column(c, width=220)
            elif c == "invoice":
                self.reports_tree.column(c, width=80, anchor=tk.CENTER)
            else:
                self.reports_tree.column(c, width=90, anchor=tk.CENTER)
        self.reports_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
        self.reports_tree.bind("<Double-1>", lambda e: self.view_report_json())

    # ---------- receipts helpers (PDFs only) ----------
    def load_receipts_list(self):
        try:
            if not hasattr(self, "receipts_listbox"):
                return
            self.receipts_listbox.delete(0, tk.END)
            # list only PDF files
            entries = [f for f in os.listdir(self.invoices_folder) if f.lower().endswith(".pdf")]
            entries.sort(reverse=True)
            for e in entries:
                self.receipts_listbox.insert(tk.END, e)
        except Exception as ex:
            print("load_receipts_list failed:", ex)

    def open_selected_receipt(self):
        try:
            sel = self.receipts_listbox.curselection()
            if not sel:
                return
            name = self.receipts_listbox.get(sel[0])
            full = os.path.join(self.invoices_folder, name)
            if os.name == "nt":
                os.startfile(full)
            elif os.name == "posix":
                import subprocess
                subprocess.Popen(["xdg-open", full])
            else:
                messagebox.showinfo("Open", full)
        except Exception as ex:
            messagebox.showerror("Error", f"Cannot open file:\n{ex}")

    def delete_selected_receipt(self):
        try:
            sel = self.receipts_listbox.curselection()
            if not sel:
                return
            name = self.receipts_listbox.get(sel[0])
            if not messagebox.askyesno("Delete", f"Delete {name}?"):
                return
            full = os.path.join(self.invoices_folder, name)
            # when deleting a PDF we may also remove the matching JSON if desired - keep JSON by default
            os.remove(full)
            self.load_receipts_list()
            # refresh reports since a PDF was removed
            self.load_reports_table()
        except Exception as ex:
            messagebox.showerror("Error", f"Failed to delete:\n{ex}")

    # ---------- reports (JSON metadata) ----------
    def load_reports_table(self):
        """Load JSON metadata files and populate reports_tree."""
        try:
            # clear existing
            for r in self.reports_tree.get_children():
                self.reports_tree.delete(r)

            json_files = [f for f in os.listdir(self.invoices_folder) if f.lower().endswith(".json")]
            json_files.sort(reverse=True)

            for jf in json_files:
                path = os.path.join(self.invoices_folder, jf)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                except Exception:
                    continue

                # parse fields safely
                customer = data.get("bill_to", {}).get("name") or data.get("bill_to", {}).get("customer") or ""
                invoice_no = data.get("invoice_number") or os.path.splitext(jf)[0]
                dt = data.get("date") or ""
                due = data.get("due_date") or data.get("due") or ""
                contact = data.get("bill_to", {}).get("contact", "") or data.get("contact", "")
                tax_pct = data.get("tax_rate") if data.get("tax_rate") is not None else data.get("tax_percent") or 0.0
                try:
                    tax_pct = float(tax_pct)
                except Exception:
                    tax_pct = 0.0
                try:
                    discount = float(data.get("discount", 0.0) or 0.0)
                except Exception:
                    discount = 0.0

                # compute subtotal from items if available
                subtotal = 0.0
                for it in data.get("items", []):
                    try:
                        q = float(it.get("qty", 0))
                        u = float(it.get("unit_price", it.get("unit", 0) or 0))
                        subtotal += q * u
                    except Exception:
                        pass
                tax_amt = subtotal * (tax_pct / 100.0)
                total = subtotal + tax_amt - discount

                row = (customer, invoice_no, dt, due, contact, f"{tax_pct:.2f}", f"{discount:.2f}", f"{subtotal:.2f}", f"{tax_amt:.2f}", f"{total:.2f}")
                self.reports_tree.insert("", "end", values=row, tags=(jf,))
        except Exception as ex:
            print("load_reports_table failed:", ex)

    def view_report_json(self):
        """Show raw JSON for selected report (popup)."""
        try:
            sel = self.reports_tree.selection()
            if not sel:
                return
            item = sel[0]
            tags = self.reports_tree.item(item, "tags") or []
            if not tags:
                messagebox.showinfo("Report", "No JSON backing file found.")
                return
            jf = tags[0]
            path = os.path.join(self.invoices_folder, jf)
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            # show in scrolled text dialog
            top = tk.Toplevel(self)
            top.title(f"JSON — {jf}")
            txt = tk.Text(top, wrap=tk.NONE)
            txt.insert("1.0", text)
            txt.pack(fill=tk.BOTH, expand=True)
            # small buttons
            btn = ttk.Frame(top)
            btn.pack(fill=tk.X)
            ttk.Button(btn, text="Close", command=top.destroy).pack(side=tk.RIGHT, padx=6, pady=6)
        except Exception as ex:
            messagebox.showerror("Error", f"Failed to open JSON:\n{ex}")

    def open_pdf_from_report(self):
        """Open the PDF file that matches the selected report (same base name)."""
        try:
            sel = self.reports_tree.selection()
            if not sel:
                return
            tags = self.reports_tree.item(sel[0], "tags") or []
            if not tags:
                messagebox.showinfo("Open PDF", "No JSON file selected.")
                return
            jf = tags[0]
            base = os.path.splitext(jf)[0]
            pdf_fn = os.path.join(self.invoices_folder, base + ".pdf")
            if not os.path.exists(pdf_fn):
                messagebox.showinfo("Open PDF", f"No PDF found for {base}.")
                return
            if os.name == "nt":
                os.startfile(pdf_fn)
            elif os.name == "posix":
                import subprocess
                subprocess.Popen(["xdg-open", pdf_fn])
            else:
                messagebox.showinfo("Open PDF", pdf_fn)
        except Exception as ex:
            messagebox.showerror("Error", f"Failed to open PDF:\n{ex}")

    def export_reports_csv(self):
        """Export reports table to CSV."""
        try:
            csv_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")])
            if not csv_path:
                return
            rows = []
            for iid in self.reports_tree.get_children():
                vals = self.reports_tree.item(iid, "values")
                rows.append(vals)
            header = ["Customer","Invoice No","Date","Due Date","Contact","Tax %","Discount","Subtotal","Tax Amt","Total"]
            with open(csv_path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(header)
                for r in rows:
                    w.writerow(r)
            messagebox.showinfo("Exported", f"Exported {len(rows)} rows to:\n{csv_path}")
        except Exception as ex:
            messagebox.showerror("Export Failed", f"{ex}")

    # ---------- invoice numbering ----------
    def invoice_list_files(self):
        files = []
        for fn in os.listdir(self.invoices_folder):
            if fn.endswith(".json"):
                files.append(fn)
        files.sort(reverse=True)
        return files

    def set_next_invoice_number(self):
        files = self.invoice_list_files()
        max_num = 0
        for fn in files:
            name = os.path.splitext(fn)[0]
            if name.isdigit():
                try:
                    max_num = max(max_num, int(name))
                except Exception:
                    pass
            else:
                digits = ''.join(ch for ch in name if ch.isdigit())
                if digits:
                    try:
                        max_num = max(max_num, int(digits))
                    except Exception:
                        pass
        next_num = max_num + 1
        try:
            self.inv_ent.delete(0, tk.END)
            self.inv_ent.insert(0, str(next_num))
        except Exception:
            pass

    # ---------- logo & signature preview ----------
    def choose_logo(self):
        fn = filedialog.askopenfilename(filetypes=[("Images","*.png;*.jpg;*.jpeg;*.gif")], title="Choose company logo")
        if not fn:
            return
        try:
            pil = Image.open(fn)
            pil = pil_trim_whitespace(pil)
            self.logo_in_memory = pil.copy()
            self.logo_path = fn
        except Exception:
            self.logo_in_memory = None
            self.logo_path = fn
        self.update_logo_preview()

    def update_logo_preview(self):
        try:
            self.logo_canvas.delete("all")
        except Exception:
            pass

        pil = None
        if getattr(self, "logo_in_memory", None):
            pil = self.logo_in_memory.copy()
        elif getattr(self, "logo_path", None):
            try:
                pil = Image.open(self.logo_path)
                pil = pil_trim_whitespace(pil)
            except Exception:
                pil = None

        if pil:
            try:
                max_w, max_h = 140, 80
                pil.thumbnail((max_w, max_h), Image.LANCZOS)
                # white background rectangle
                self.logo_canvas.create_rectangle(0, 0, max_w, max_h, fill="#ffffff", outline="")
                self.logo_thumbnail = ImageTk.PhotoImage(pil)
                cx = max_w // 2
                cy = max_h // 2
                self.logo_canvas.create_image(cx, cy, image=self.logo_thumbnail, anchor="center")
            except Exception:
                self.logo_canvas.create_text(70, 40, text=os.path.basename(getattr(self, "logo_path", "")), fill="#333")
        else:
            try:
                self.logo_canvas.create_rectangle(0, 0, 140, 80, fill="#ffffff", outline="")
                self.logo_canvas.create_text(70, 40, text="No logo", fill="#777")
            except Exception:
                pass

    def clear_logo(self):
        self.logo_path = None
        self.logo_in_memory = None
        self.logo_thumbnail = None
        try:
            self.logo_canvas.delete("all")
            self.logo_canvas.create_text(70, 40, text="No logo", fill="#777")
        except Exception:
            pass

    def update_signature_preview(self):
        if getattr(self, "signature_image", None):
            try:
                pil = self.signature_image.copy()
                pil.thumbnail((220, 80), Image.LANCZOS)
                self.signature_thumbnail = ImageTk.PhotoImage(pil)
                self.sig_preview_label.configure(image=self.signature_thumbnail, text="")
            except Exception:
                self.sig_preview_label.configure(text="Signature (in memory)", image="")
        else:
            self.sig_preview_label.configure(text="No signature", image="")

    def clear_signature(self):
        self.signature_image = None
        self.signature_thumbnail = None
        self.update_signature_preview()

    # ---------- items ----------
    def open_add_item(self):
        dlg = AddItemDialog(self, title="Add Item")
        if getattr(dlg, "result", None):
            it = dlg.result
            self.items.append(it)
            amt = it["qty"] * it["unit_price"]
            qty_display = str(int(it["qty"]) if float(it["qty"]).is_integer() else it["qty"])
            self.tree.insert("", "end", values=("✖", it["desc"], qty_display, f"{it['unit_price']:.2f}", f"{amt:.2f}"))
            self.update_totals()

    def remove_selected_item(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        self.tree.delete(sel[0])
        if idx < len(self.items):
            self.items.pop(idx)
        self.update_totals()

    # handle click on tree (delete column)
    def on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        row_id = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)  # "#1" is delete column
        if col == "#1" and row_id:
            if not messagebox.askyesno("Delete item", "Remove this item?"):
                return
            try:
                idx = self.tree.index(row_id)
                self.tree.delete(row_id)
                if idx < len(self.items):
                    self.items.pop(idx)
            except Exception as ex:
                print("Failed to remove item:", ex)
            self.update_totals()

    # ---------- signature dialog ----------
    def open_signature(self):
        dlg = SignatureCanvas(self, width=600, height=180)
        self.wait_window(dlg)
        if getattr(dlg, "result_image", None):
            self.signature_image = dlg.result_image.copy()
            self.update_signature_preview()

    # ---------- build / save invoice ----------
    def build_invoice_data(self):
        inv = {
            "company_name": self.from_txt.get("1.0", tk.END).strip().splitlines()[0] if self.from_txt.get("1.0", tk.END).strip() else "",
            "company_address": self.from_txt.get("1.0", tk.END).strip(),
            "invoice_number": self.inv_ent.get().strip(),
            "date": self.date_ent.get_date().isoformat() if hasattr(self.date_ent, "get_date") else self.date_ent.get().strip(),
            "bill_to": {"name": self.bill_txt.get("1.0", tk.END).strip().splitlines()[0], "contact": self.contact_ent.get().strip()},
            "items": self.items,
            "tax_rate": float(self.tax_ent.get().strip() or 0.0),
            "discount": float(self.disc_ent.get().strip() or 0.0),
            "notes": self.terms_txt.get("1.0", tk.END).strip(),
            "logo_path": getattr(self, "logo_path", None),
            "logo_image": getattr(self, "logo_in_memory", None),
            "signature_path": None
        }
        if getattr(self, "signature_image", None):
            inv["signature_image"] = self.signature_image.copy()
        else:
            inv["signature_image"] = None
        inv["due_date"] = self.due_ent.get_date().isoformat() if hasattr(self.due_ent, "get_date") else self.due_ent.get().strip()
        return inv

    def save_invoice_fullwidth(self):
        if not self.items:
            if not messagebox.askyesno("No items", "There are no items. Save anyway?"):
                return
        inv = self.build_invoice_data()
        base = inv.get("invoice_number", f"inv-{date.today().isoformat()}")
        safe = "".join(c for c in base if c.isalnum() or c in "-_")
        pdf_fn = os.path.join(self.invoices_folder, safe + ".pdf")
        json_fn = os.path.join(self.invoices_folder, safe + ".json")

        try:
            make_invoice(pdf_fn, inv)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create PDF:\n{e}")
            return

        safe_inv = dict(inv)
        safe_inv.pop("signature_image", None)
        safe_inv.pop("logo_image", None)
        if getattr(self, "signature_image", None) and not safe_inv.get("signature_path"):
            safe_inv["signature_saved_in_pdf_only"] = True

        try:
            with open(json_fn, "w", encoding="utf-8") as f:
                json.dump(safe_inv, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showwarning("Warning", f"PDF saved but failed to save JSON metadata:\n{e}")
            return

        messagebox.showinfo("Saved", f"Saved PDF:\n{pdf_fn}\n\nSaved JSON:\n{json_fn}")
        self.load_receipts_list()
        self.load_reports_table()
        try:
            self.set_next_invoice_number()
        except Exception:
            pass

    # ---------- totals ----------
    def update_totals(self):
        subtotal = 0.0
        for it in self.items:
            try:
                subtotal += float(it.get("qty",0)) * float(it.get("unit_price",0.0))
            except Exception:
                pass
        self.subtotal_var.set(currency(subtotal))

        # tax interpreted as percent (user enters e.g. 6 for 6%)
        try:
            tax_percent = float(self.tax_ent.get().strip() or 0)
        except Exception:
            tax_percent = 0.0
        try:
            disc = float(self.disc_ent.get().strip() or 0)
        except Exception:
            disc = 0.0

        tax_amount = subtotal * (tax_percent / 100.0)
        total = subtotal + tax_amount - disc

        # update displayed values
        self.total_var.set(currency(total))

    def reset_form(self):
        self.from_txt.delete("1.0", tk.END)
        self.bill_txt.delete("1.0", tk.END)
        self.from_txt.insert("1.0", "Your Company Name\nAddress line 1\nAddress line 2")
        self.bill_txt.insert("1.0", "Customer Name")
        self.items = []
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.clear_logo()
        self.clear_signature()
        self.set_next_invoice_number()
        self.update_totals()

# ---------- Signature canvas & AddItemDialog ----------
class SignatureCanvas(tk.Toplevel):
    def __init__(self, parent, width=600, height=180, bg="white"):
        super().__init__(parent)
        self.title("Sign here")
        self.resizable(False, False)
        self.canvas_width = width
        self.canvas_height = height
        self.bg = bg

        self.image = Image.new("RGB", (width, height), bg)
        self.draw = ImageDraw.Draw(self.image)

        self.canvas = tk.Canvas(self, width=width, height=height, bg=bg, cursor="cross")
        self.canvas.pack()
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, pady=4)
        ttk.Button(btn_frame, text="Clear", command=self.clear).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Save & Close", command=self.save_and_close).pack(side=tk.RIGHT, padx=4)

        self.old_x = None
        self.old_y = None
        self.pen_width = 2
        self.pen_fill = "black"

        self.canvas.bind("<ButtonPress-1>", self.pen_down)
        self.canvas.bind("<B1-Motion>", self.pen_move)
        self.canvas.bind("<ButtonRelease-1>", self.pen_up)

        self.result_image = None

    def pen_down(self, event):
        self.old_x = event.x
        self.old_y = event.y

    def pen_move(self, event):
        if self.old_x is not None and self.old_y is not None:
            x, y = event.x, event.y
            self.canvas.create_line(self.old_x, self.old_y, x, y, width=self.pen_width, fill=self.pen_fill, capstyle=tk.ROUND, smooth=True)
            self.draw.line([(self.old_x, self.old_y), (x, y)], fill=self.pen_fill, width=self.pen_width)
            self.old_x = x
            self.old_y = y

    def pen_up(self, event):
        self.old_x = None
        self.old_y = None

    def clear(self):
        self.canvas.delete("all")
        self.image = Image.new("RGB", (self.canvas_width, self.canvas_height), self.bg)
        self.draw = ImageDraw.Draw(self.image)

    def save_and_close(self):
        self.result_image = self.image.copy()
        self.destroy()

class AddItemDialog(simpledialog.Dialog):
    def body(self, master):
        ttk.Label(master, text="Description:").grid(row=0, column=0, sticky=tk.W)
        self.desc = ttk.Entry(master, width=50); self.desc.grid(row=0, column=1, padx=4, pady=2)
        ttk.Label(master, text="Qty:").grid(row=1, column=0, sticky=tk.W)
        self.qty = ttk.Entry(master, width=10); self.qty.grid(row=1, column=1, sticky=tk.W, padx=4, pady=2)
        self.qty.insert(0, "1")
        ttk.Label(master, text="Unit Price:").grid(row=2, column=0, sticky=tk.W)
        self.unit = ttk.Entry(master, width=15); self.unit.grid(row=2, column=1, sticky=tk.W, padx=4, pady=2)
        self.unit.insert(0, "0.00")
        return self.desc

    def apply(self):
        try:
            qty = float(self.qty.get())
            unit = float(self.unit.get())
            desc = self.desc.get().strip()
            if not desc:
                raise ValueError("Description empty")
            self.result = {"desc": desc, "qty": qty, "unit_price": unit}
        except Exception as e:
            messagebox.showerror("Invalid", f"Invalid item: {e}")
            self.result = None

# Run
if __name__ == "__main__":
    app = InvoiceApp()
    app.mainloop()
