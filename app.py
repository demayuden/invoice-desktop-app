# app.py
"""
MyInvoice — Sidebar version (Tkinter)
Place icons in ./assets/icons/: home.png, invoice.png, receipts.png, reports.png, back.png
"""
import os
import sys
import io
import csv
import json
import shutil
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

# ---------- Styles ----------
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="InvoiceTitle", parent=styles["Title"], alignment=0, fontSize=16, leading=18))
styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontSize=9, leading=11))

# ---------- Utility functions ----------
def ensure_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass

def get_user_writable_invoices_dir(app_name="MyInvoice"):
    try:
        base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(__file__)
    except Exception:
        base = os.getcwd()

    candidate = os.path.join(base, "invoices")
    try:
        os.makedirs(candidate, exist_ok=True)
        return candidate
    except PermissionError:
        pass
    except Exception:
        pass

    localapp = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    fallback_base = os.path.join(localapp, app_name)
    invoices_fallback = os.path.join(fallback_base, "invoices")
    try:
        os.makedirs(invoices_fallback, exist_ok=True)
        return invoices_fallback
    except Exception as e:
        try:
            cwd_candidate = os.path.join(os.getcwd(), "invoices")
            os.makedirs(cwd_candidate, exist_ok=True)
            return cwd_candidate
        except Exception:
            raise RuntimeError(f"Failed to create invoices folder (tried {candidate} and {invoices_fallback}): {e}")

def migrate_app_invoices_if_necessary(source_dir, target_dir):
    try:
        if not os.path.isdir(source_dir) or os.path.abspath(source_dir) == os.path.abspath(target_dir):
            return
        for fn in os.listdir(source_dir):
            if not fn.lower().endswith((".pdf", ".json")):
                continue
            src = os.path.join(source_dir, fn)
            dst = os.path.join(target_dir, fn)
            if not os.path.exists(dst):
                try:
                    shutil.move(src, dst)
                except Exception:
                    pass
    except Exception:
        pass

def currency(v):
    try:
        return f"RM {float(v):,.2f}"
    except Exception:
        return "RM 0.00"

def pil_trim_whitespace(pil, bg_color=(255,255,255)):
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
    if not pil:
        return None
    try:
        w_px, h_px = pil.size
        if w_px <= 0 or h_px <= 0:
            return None
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

# ---------- PDF generation ----------
def make_invoice(path, invoice):
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

    # logo
    logo_src = invoice.get("logo_image") or invoice.get("logo_path")
    rl_logo = get_rl_image(logo_src, max_w_mm=45, max_h_mm=30)
    if rl_logo:
        elements.append(rl_logo)
        elements.append(Spacer(1, 6))

    # company address
    elements.append(Paragraph(invoice.get('company_name',''), styles['InvoiceTitle']))
    elements.append(Paragraph(invoice.get('company_address',''), styles['Normal']))
    elements.append(Spacer(1, 8))

    # meta
    meta_tbl = [
        ['Invoice No:', invoice.get('invoice_number',''), 'Date:', invoice.get('date','')],
        ['Bill To:', invoice.get('bill_to',{}).get('name',''), 'Due Date:', invoice.get('due_date','')],
        ['Contact:', invoice.get('bill_to',{}).get('contact',''), '', '']
    ]
    meta_table = Table(meta_tbl, colWidths=[30*mm, 80*mm, 25*mm, 50*mm])
    meta_table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
                                    ('FONTNAME',(0,0),(-1,-1),'Helvetica'),
                                    ('FONTSIZE',(0,0),(-1,-1),10),
                                    ('BOTTOMPADDING', (0,0), (-1,-1), 6),]))
    elements.append(meta_table)
    elements.append(Spacer(1, 10))

    # items
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
    totals_table.setStyle(TableStyle([('ALIGN',(2,0),(-1,-1),'RIGHT'),
                                      ('FONTNAME',(2,0),(-1,-1),'Helvetica'),
                                      ('FONTSIZE',(2,0),(-1,-1),10),]))
    elements.append(totals_table)
    elements.append(Spacer(1,12))

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

# ---------- Main App with Sidebar ----------
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets", "icons")

class SidebarApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MyInvoice App")
        self.geometry("1180x760")
        self.minsize(980, 620)

        # shared data
        self.items = []
        self.logo_path = None
        self.logo_in_memory = None
        self.logo_thumbnail = None
        self.signature_image = None
        self.signature_thumbnail = None

        # determine invoices folder (use module-level helper)
        try:
            selected = get_user_writable_invoices_dir("MyInvoice")
        except Exception:
            selected = os.path.join(os.path.dirname(__file__), "invoices")
        old_dev_invoices = os.path.join(os.path.dirname(__file__), "invoices")
        if os.path.abspath(old_dev_invoices) != os.path.abspath(selected):
            try:
                migrate_app_invoices_if_necessary(old_dev_invoices, selected)
            except Exception:
                pass

        self.invoices_folder = selected
        ensure_folder(self.invoices_folder)

        # trash folder + last_deleted for undo
        self.trash_folder = os.path.join(self.invoices_folder, ".trash")
        ensure_folder(self.trash_folder)
        self.last_deleted = None  # tuple (moved_pdf_path, moved_json_path)

        self._setup_style()
        self._create_layout()
        self.set_next_invoice_number()
        self.load_receipts_list()
        self.load_reports_table()
        self.update_totals()

    def _setup_style(self):
        s = ttk.Style(self)
        try:
            s.theme_use('clam')
        except Exception:
            pass
        s.configure("Sidebar.TFrame", background="#f4f4f6")
        s.configure("Accent.TButton", foreground="white", background="#0a84ff")
        s.map("Accent.TButton", background=[('active', '#0666cc')])

    def _create_layout(self):
        # top bar
        top = ttk.Frame(self, padding=6)
        top.pack(side="top", fill="x")
        ttk.Label(top, text="MyInvoice", font=("Segoe UI", 14, "bold")).pack(side="left")

        # main body
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        # sidebar
        sidebar = ttk.Frame(body, width=160, style="Sidebar.TFrame")
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # content container
        self.container = ttk.Frame(body)
        self.container.pack(side="left", fill="both", expand=True)

        # load icons (keep them on self to avoid GC)
        def load_icon(name, size=(26,26)):
            p = os.path.join(ASSETS_DIR, name)
            if not os.path.exists(p):
                print("Icon not found:", p)
                return None
            try:
                im = Image.open(p).convert("RGBA")
                im.thumbnail(size, Image.LANCZOS)
                return ImageTk.PhotoImage(im)
            except Exception as e:
                print("Icon load error:", p, "->", e)
                return None

        self.icons = {
            "home": load_icon("home.png"),
            "invoice": load_icon("invoice.png"),
            "receipts": load_icon("receipts.png"),
            "reports": load_icon("reports.png"),
            "back": load_icon("back.png")
        }

        # sidebar buttons
        ttk.Button(sidebar, text=" Home", image=self.icons["home"], compound="left", command=lambda: self.new_invoice()).pack(fill="x", padx=10, pady=(12,6))
        ttk.Button(sidebar, text=" Invoice", image=self.icons["invoice"], compound="left", command=lambda: self.show_page("invoice")).pack(fill="x", padx=10, pady=6)
        ttk.Button(sidebar, text=" Receipts", image=self.icons["receipts"], compound="left", command=lambda: self.show_page("receipts")).pack(fill="x", padx=10, pady=6)
        ttk.Button(sidebar, text=" Reports", image=self.icons["reports"], compound="left", command=lambda: self.show_page("reports")).pack(fill="x", padx=10, pady=6)
        ttk.Separator(sidebar, orient="horizontal").pack(fill="x", pady=12, padx=8)

        # create pages (frames)
        self.pages = {}
        self.pages["home"] = HomePage(self.container, self)
        self.pages["invoice"] = InvoicePage(self.container, self)
        self.pages["receipts"] = ReceiptsPage(self.container, self)
        self.pages["reports"] = ReportsPage(self.container, self)

        for p in self.pages.values():
            p.place(relx=0, rely=0, relwidth=1, relheight=1)

        # show default
        self.show_page("home")

    def show_page(self, name):
        page = self.pages.get(name)
        if page:
            page.lift()
        if name == "receipts":
            self.load_receipts_list()
        if name == "reports":
            self.load_reports_table()

    # ---------- New invoice helper ----------
    def new_invoice(self):
        try:
            inv_page = self.pages.get("invoice")
            if inv_page:
                inv_page.clear_form()
                self.set_next_invoice_number()
                self.show_page("invoice")
        except Exception as ex:
            print("new_invoice failed:", ex)

    # ----------------- Receipt/Report helpers ---------------
    def load_receipts_list(self):
        try:
            lb = getattr(self, "receipts_listbox", None)
            if not lb:
                return
            lb.delete(0, tk.END)
            entries = [f for f in os.listdir(self.invoices_folder) if f.lower().endswith(".pdf")]
            entries.sort(reverse=True)
            for e in entries:
                lb.insert(tk.END, e)
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
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", full])
            elif os.name == "posix":
                import subprocess
                subprocess.Popen(["xdg-open", full])
            else:
                messagebox.showinfo("Open", full)
        except Exception as ex:
            messagebox.showerror("Error", f"Cannot open file:\n{ex}")

    def edit_selected_receipt(self):
        """
        Load selected PDF's matching JSON metadata and open it in the Invoice page for editing.
        Overwrite same PDF/JSON on save (invoice number remains same).
        """
        try:
            sel = self.receipts_listbox.curselection()
            if not sel:
                messagebox.showinfo("Edit", "No receipt selected.")
                return
            name = self.receipts_listbox.get(sel[0])
            base = os.path.splitext(name)[0]
            json_path = os.path.join(self.invoices_folder, base + ".json")
            pdf_path = os.path.join(self.invoices_folder, base + ".pdf")
            if not os.path.exists(json_path):
                messagebox.showwarning("Edit", f"No JSON metadata found for {name}.\nCannot edit PDF without metadata.")
                return
            try:
                with open(json_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception as e:
                messagebox.showerror("Edit", f"Failed to load JSON metadata:\n{e}")
                return

            # call invoice page loader
            inv_page = self.pages.get("invoice")
            if not inv_page:
                messagebox.showerror("Edit", "Invoice page not available.")
                return
            inv_page.load_invoice_data(data, editing_base=base)
            self.show_page("invoice")
        except Exception as ex:
            messagebox.showerror("Edit Failed", f"{ex}")

    def delete_selected_receipt(self):
        try:
            sel = self.receipts_listbox.curselection()
            if not sel:
                return
            name = self.receipts_listbox.get(sel[0])
            if not messagebox.askyesno("Delete", f"Delete {name}? This will move the matching JSON to trash and allow Undo."):
                return
            full_pdf = os.path.join(self.invoices_folder, name)
            base = os.path.splitext(name)[0]
            json_path = os.path.join(self.invoices_folder, base + ".json")

            def move_to_trash(src):
                if not os.path.exists(src):
                    return None
                dest = os.path.join(self.trash_folder, os.path.basename(src))
                if os.path.exists(dest):
                    i = 1
                    base_n, ext_n = os.path.splitext(os.path.basename(src))
                    while True:
                        dest_try = os.path.join(self.trash_folder, f"{base_n}_{i}{ext_n}")
                        if not os.path.exists(dest_try):
                            dest = dest_try
                            break
                        i += 1
                try:
                    os.replace(src, dest)
                    return dest
                except Exception:
                    try:
                        shutil.copy2(src, dest)
                        os.remove(src)
                        return dest
                    except Exception as e:
                        print("Failed moving to trash:", e)
                        return None

            moved_pdf = move_to_trash(full_pdf)
            moved_json = None
            if os.path.exists(json_path):
                moved_json = move_to_trash(json_path)

            if moved_pdf or moved_json:
                self.last_deleted = (moved_pdf, moved_json)
            else:
                self.last_deleted = None

            self.load_receipts_list()
            self.load_reports_table()

            if self.last_deleted:
                messagebox.showinfo("Deleted", f"Moved to Trash. You can undo the last delete (Receipts -> Undo Delete).")
        except Exception as ex:
            messagebox.showerror("Error", f"Failed to delete:\n{ex}")

    def undo_delete(self):
        if not getattr(self, "last_deleted", None):
            messagebox.showinfo("Undo", "Nothing to undo.")
            return

        moved_pdf, moved_json = self.last_deleted
        restored = []
        errors = []

        def restore(src):
            if not src or not os.path.exists(src):
                return None
            dest = os.path.join(self.invoices_folder, os.path.basename(src))
            if os.path.exists(dest):
                i = 1
                base, ext = os.path.splitext(os.path.basename(src))
                while True:
                    dest_try = os.path.join(self.invoices_folder, f"{base}_restored_{i}{ext}")
                    if not os.path.exists(dest_try):
                        dest = dest_try
                        break
                    i += 1
            try:
                os.replace(src, dest)
                return dest
            except Exception:
                try:
                    shutil.copy2(src, dest)
                    os.remove(src)
                    return dest
                except Exception as e:
                    return str(e)

        if moved_pdf:
            res = restore(moved_pdf)
            if isinstance(res, str) and not os.path.exists(res):
                errors.append(f"PDF: {res}")
            else:
                restored.append(res)
        if moved_json:
            res = restore(moved_json)
            if isinstance(res, str) and not os.path.exists(res):
                errors.append(f"JSON: {res}")
            else:
                restored.append(res)

        if restored:
            self.last_deleted = None
            self.load_receipts_list()
            self.load_reports_table()
            messagebox.showinfo("Undo", f"Restored {len(restored)} file(s).")
        else:
            messagebox.showerror("Undo Failed", f"Failed to restore files: {errors}")

    # ---------- reports ----------
    def load_reports_table(self):
        try:
            tree = getattr(self, "reports_tree", None)
            if not tree:
                return
            for r in tree.get_children():
                tree.delete(r)
            json_files = [f for f in os.listdir(self.invoices_folder) if f.lower().endswith(".json")]
            json_files.sort(reverse=True)
            for jf in json_files:
                path = os.path.join(self.invoices_folder, jf)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                except Exception:
                    continue
                customer = data.get("bill_to", {}).get("name","")
                invoice_no = data.get("invoice_number") or os.path.splitext(jf)[0]
                dt = data.get("date","")
                due = data.get("due_date") or ""
                contact = data.get("bill_to",{}).get("contact","")
                tax_pct = data.get("tax_rate") if data.get("tax_rate") is not None else data.get("tax_percent") or 0.0
                try:
                    tax_pct = float(tax_pct)
                except Exception:
                    tax_pct = 0.0
                try:
                    discount = float(data.get("discount", 0.0) or 0.0)
                except Exception:
                    discount = 0.0
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
                tree.insert("", "end", values=row, tags=(jf,))
        except Exception as ex:
            print("load_reports_table failed:", ex)

    def open_pdf_from_report(self):
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
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", pdf_fn])
            elif os.name == "posix":
                import subprocess
                subprocess.Popen(["xdg-open", pdf_fn])
            else:
                messagebox.showinfo("Open PDF", pdf_fn)
        except Exception as ex:
            messagebox.showerror("Error", f"Failed to open PDF:\n{ex}")

    def export_reports_csv(self):
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
            self.pages["invoice"].inv_ent.delete(0, tk.END)
            self.pages["invoice"].inv_ent.insert(0, str(next_num))
        except Exception:
            pass

    # ---------- totals (shared) ----------
    def update_totals(self):
        subtotal = 0.0
        for it in self.items:
            try:
                subtotal += float(it.get("qty",0)) * float(it.get("unit_price",0.0))
            except Exception:
                pass
        try:
            self.pages["invoice"].subtotal_var.set(currency(subtotal))
        except Exception:
            pass

        try:
            tax_percent = float(self.pages["invoice"].tax_ent.get().strip() or 0)
        except Exception:
            tax_percent = 0.0
        try:
            disc = float(self.pages["invoice"].disc_ent.get().strip() or 0)
        except Exception:
            disc = 0.0

        tax_amount = subtotal * (tax_percent / 100.0)
        total = subtotal + tax_amount - disc
        try:
            self.pages["invoice"].total_var.set(currency(total))
        except Exception:
            pass

# ---------- Pages (Frames) ----------
class HomePage(ttk.Frame):
    def __init__(self, parent, app: SidebarApp):
        super().__init__(parent)
        ttk.Label(self, text="Welcome to MyInvoice App", font=("Segoe UI", 18, "bold")).pack(pady=24)
        ttk.Button(self, text="Create New Invoice", command=lambda: app.new_invoice()).pack()

class InvoicePage(ttk.Frame):
    def __init__(self, parent, app: SidebarApp):
        super().__init__(parent)
        self.app = app
        # track editing base filename (None when creating new)
        self.editing_base = None

        # Top left: From / Bill To
        top = ttk.Frame(self)
        top.pack(fill=tk.X, pady=(0,8), padx=8)

        left_top = ttk.Frame(top)
        left_top.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(left_top, text="From", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        self.from_txt = tk.Text(left_top, height=5, wrap=tk.WORD)
        self.from_txt.pack(fill=tk.X, pady=4)
        self.from_txt.insert("1.0", "Your Company Name\nAddress line 1\nAddress line 2")

        ttk.Label(left_top, text="Bill To", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(6,0))
        self.bill_txt = tk.Text(left_top, height=4, wrap=tk.WORD)
        self.bill_txt.pack(fill=tk.X, pady=4)
        self.bill_txt.insert("1.0", "Customer Name")

        # right metadata and logo
        right_top = ttk.Frame(top, width=360)
        right_top.pack(side=tk.RIGHT, fill=tk.Y, padx=(8,0))
        right_top.pack_propagate(False)

        # Logo frame: reduced height to avoid covering meta fields
        logo_frame = ttk.Frame(right_top, relief=tk.RIDGE, padding=8)
        logo_frame.pack(fill=tk.X)
        ttk.Label(logo_frame, text="Logo", font=("Segoe UI", 10, "bold")).pack()
        logo_frame.config(height=100)
        logo_frame.pack_propagate(False)

        btn_row = ttk.Frame(logo_frame)
        btn_row.pack(fill=tk.X, pady=6)
        ttk.Button(btn_row, text="Select Logo", command=self.choose_logo).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Clear", command=self.clear_logo).pack(side=tk.LEFT, padx=6)

        self.logo_canvas = tk.Canvas(logo_frame, width=120, height=60, bg="#ffffff", highlightthickness=0)
        self.logo_canvas.pack(pady=(6,0))
        try:
            self.logo_canvas.create_text(60, 30, text="No logo", fill="#777")
        except Exception:
            pass

        # meta placed directly below logo frame
        meta_frame = ttk.Frame(right_top, padding=(0,8))
        meta_frame.pack(fill=tk.X, pady=6)
        ttk.Label(meta_frame, text="Invoice #").grid(row=0, column=0, sticky=tk.W)
        self.inv_ent = ttk.Entry(meta_frame, width=20); self.inv_ent.grid(row=0, column=1, padx=6, pady=2)
        ttk.Label(meta_frame, text="Invoice Date").grid(row=1, column=0, sticky=tk.W)
        self.date_ent = DateEntry(meta_frame, width=18, date_pattern='yyyy-mm-dd'); self.date_ent.grid(row=1, column=1, padx=6, pady=2)
        self.date_ent.set_date(date.today())
        ttk.Label(meta_frame, text="Due Date").grid(row=2, column=0, sticky=tk.W)
        self.due_ent = DateEntry(meta_frame, width=18, date_pattern='yyyy-mm-dd'); self.due_ent.grid(row=2, column=1, padx=6, pady=2)
        self.due_ent.set_date(date.today() + timedelta(days=15))
        ttk.Label(meta_frame, text="Contact").grid(row=3, column=0, sticky=tk.W)
        self.contact_ent = ttk.Entry(meta_frame, width=20); self.contact_ent.grid(row=3, column=1, padx=6, pady=2)

        # Items area
        items_frame = ttk.LabelFrame(self, text="Description / Amount", padding=8)
        items_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0,6))

        toolbar = ttk.Frame(items_frame)
        toolbar.pack(fill=tk.X, pady=(0,6))
        ttk.Button(toolbar, text="+ Add New Item", command=self.open_add_item).pack(side=tk.LEFT)

        self.tree = ttk.Treeview(items_frame, columns=("del","desc","qty","unit","amt"), show="headings", selectmode="browse")
        self.tree.heading("del", text=""); self.tree.column("del", width=30, anchor=tk.CENTER, stretch=False)
        self.tree.heading("desc", text="Description"); self.tree.heading("qty", text="Qty")
        self.tree.heading("unit", text="Unit Price"); self.tree.heading("amt", text="Amount")
        self.tree.column("desc", width=540); self.tree.column("qty", width=80, anchor=tk.E)
        self.tree.column("unit", width=120, anchor=tk.E); self.tree.column("amt", width=120, anchor=tk.E)
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<Delete>", lambda e: self.remove_selected_item())

        right_tot = ttk.Frame(items_frame, width=300)
        right_tot.pack(side=tk.RIGHT, fill=tk.Y, padx=(8,0)); right_tot.pack_propagate(False)
        ttk.Label(right_tot, text="Subtotal", font=("Segoe UI", 10)).pack(anchor=tk.E, pady=(10,0), padx=6)
        self.subtotal_var = tk.StringVar(value="RM 0.00"); ttk.Label(right_tot, textvariable=self.subtotal_var, font=("Segoe UI", 10)).pack(anchor=tk.E, padx=6)
        ttk.Label(right_tot, text="Tax (%)", font=("Segoe UI", 10)).pack(anchor=tk.E, pady=(8,0), padx=6)
        self.tax_ent = ttk.Entry(right_tot, width=10); self.tax_ent.pack(anchor=tk.E, padx=6); self.tax_ent.insert(0, "0.00")
        ttk.Label(right_tot, text="Discount", font=("Segoe UI", 10)).pack(anchor=tk.E, pady=(8,0), padx=6)
        self.disc_ent = ttk.Entry(right_tot, width=10); self.disc_ent.pack(anchor=tk.E, padx=6); self.disc_ent.insert(0, "0.00")
        ttk.Separator(right_tot, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Label(right_tot, text="TOTAL", font=("Segoe UI", 12, "bold")).pack(anchor=tk.E)
        self.total_var = tk.StringVar(value="RM 0.00"); ttk.Label(right_tot, textvariable=self.total_var, font=("Segoe UI", 14, "bold")).pack(anchor=tk.E, padx=6)

        self.tax_ent.bind("<KeyRelease>", lambda e: app.update_totals()); self.tax_ent.bind("<FocusOut>", lambda e: app.update_totals())
        self.disc_ent.bind("<KeyRelease>", lambda e: app.update_totals()); self.disc_ent.bind("<FocusOut>", lambda e: app.update_totals())

        # bottom: terms and signature
        bottom = ttk.Frame(self); bottom.pack(fill=tk.X, pady=(6,8), padx=8)
        left_bot = ttk.Frame(bottom); left_bot.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ttk.Label(left_bot, text="Terms and Conditions", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        self.terms_txt = tk.Text(left_bot, height=4); self.terms_txt.pack(fill=tk.BOTH, expand=True, pady=4); self.terms_txt.insert("1.0", "Payment is due within 15 days")

        right_bot = ttk.Frame(bottom, width=340); right_bot.pack(side=tk.RIGHT, fill=tk.Y, padx=(8,0)); right_bot.pack_propagate(False)
        sig_frame = ttk.Frame(right_bot, relief=tk.RIDGE, padding=8); sig_frame.pack(fill=tk.X)
        ttk.Label(sig_frame, text="Signature", font=("Segoe UI", 10, "bold")).pack()
        ttk.Button(sig_frame, text="✍ Sign here", command=self.open_signature).pack(pady=6)
        ttk.Button(sig_frame, text="Clear", command=self.clear_signature).pack()
        self.sig_preview_label = ttk.Label(sig_frame, text="No signature"); self.sig_preview_label.pack(pady=(6,0))

        save_frame = ttk.Frame(self)
        save_frame.pack(fill=tk.X, pady=(10,8), padx=8)
        ttk.Button(save_frame, text="💾 Save Invoice", command=self.save_invoice_fullwidth, style="Accent.TButton").pack(fill=tk.X)

    # ---------- logo & signature helpers (InvoicePage level) ----------
    def choose_logo(self):
        fn = filedialog.askopenfilename(filetypes=[("Images","*.png;*.jpg;*.jpeg;*.gif")], title="Choose company logo")
        if not fn:
            return
        try:
            pil = Image.open(fn)
            pil = pil_trim_whitespace(pil)
            self.app.logo_in_memory = pil.copy()
            self.app.logo_path = fn
        except Exception:
            self.app.logo_in_memory = None
            self.app.logo_path = fn
        self.update_logo_preview()

    def update_logo_preview(self):
        try:
            self.logo_canvas.delete("all")
        except Exception:
            pass

        pil = None
        if getattr(self.app, "logo_in_memory", None):
            pil = self.app.logo_in_memory.copy()
        elif getattr(self.app, "logo_path", None):
            try:
                pil = Image.open(self.app.logo_path)
                pil = pil_trim_whitespace(pil)
            except Exception:
                pil = None

        if pil:
            try:
                max_w, max_h = 120, 60
                pil.thumbnail((max_w, max_h), Image.LANCZOS)
                self.logo_canvas.create_rectangle(0, 0, max_w, max_h, fill="#ffffff", outline="")
                self.logo_thumbnail = ImageTk.PhotoImage(pil)
                cx = max_w // 2; cy = max_h // 2
                self.logo_canvas.create_image(cx, cy, image=self.logo_thumbnail, anchor="center")
            except Exception:
                self.logo_canvas.create_text(60, 30, text=os.path.basename(getattr(self.app, "logo_path", "")), fill="#333")
        else:
            try:
                self.logo_canvas.create_rectangle(0, 0, 120, 60, fill="#ffffff", outline="")
                self.logo_canvas.create_text(60, 30, text="No logo", fill="#777")
            except Exception:
                pass

    def clear_logo(self):
        self.app.logo_path = None
        self.app.logo_in_memory = None
        self.logo_thumbnail = None
        try:
            self.logo_canvas.delete("all")
            self.logo_canvas.create_text(60, 30, text="No logo", fill="#777")
        except Exception:
            pass

    # ---------- items ----------
    def open_add_item(self):
        dlg = AddItemDialog(self, title="Add Item")
        if getattr(dlg, "result", None):
            it = dlg.result
            self.app.items.append(it)
            amt = it["qty"] * it["unit_price"]
            qty_display = str(int(it["qty"]) if float(it["qty"]).is_integer() else it["qty"])
            self.tree.insert("", "end", values=("✖", it["desc"], qty_display, f"{it['unit_price']:.2f}", f"{amt:.2f}"))
            self.app.update_totals()

    def remove_selected_item(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        self.tree.delete(sel[0])
        if idx < len(self.app.items):
            self.app.items.pop(idx)
        self.app.update_totals()

    def on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        row_id = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if col == "#1" and row_id:
            if not messagebox.askyesno("Delete item", "Remove this item?"):
                return
            try:
                idx = self.tree.index(row_id)
                self.tree.delete(row_id)
                if idx < len(self.app.items):
                    self.app.items.pop(idx)
            except Exception as ex:
                print("Failed to remove item:", ex)
            self.app.update_totals()

    # ---------- signature ----------
    def open_signature(self):
        dlg = SignatureCanvas(self, width=600, height=180)
        self.wait_window(dlg)
        if getattr(dlg, "result_image", None):
            self.app.signature_image = dlg.result_image.copy()
            self.update_signature_preview()

    def update_signature_preview(self):
        if getattr(self.app, "signature_image", None):
            try:
                pil = self.app.signature_image.copy()
                pil.thumbnail((220, 80), Image.LANCZOS)
                self.app.signature_thumbnail = ImageTk.PhotoImage(pil)
                self.sig_preview_label.configure(image=self.app.signature_thumbnail, text="")
            except Exception:
                self.sig_preview_label.configure(text="Signature (in memory)", image="")
        else:
            self.sig_preview_label.configure(text="No signature", image="")

    def clear_signature(self):
        self.app.signature_image = None
        self.app.signature_thumbnail = None
        self.update_signature_preview()

    # ---------- build/save invoice ----------
    def build_invoice_data(self):
        from_text = self.from_txt.get("1.0", tk.END).strip()
        inv = {
            "company_name": from_text.splitlines()[0] if from_text else "",
            "company_address": from_text,
            "invoice_number": self.inv_ent.get().strip(),
            "date": self.date_ent.get_date().isoformat() if hasattr(self.date_ent, "get_date") else self.date_ent.get().strip(),
            "bill_to": {"name": self.bill_txt.get("1.0", tk.END).strip().splitlines()[0], "contact": self.contact_ent.get().strip()},
            "items": self.app.items,
            "tax_rate": float(self.tax_ent.get().strip() or 0.0),
            "discount": float(self.disc_ent.get().strip() or 0.0),
            "notes": self.terms_txt.get("1.0", tk.END).strip(),
            "logo_path": getattr(self.app, "logo_path", None),
            "logo_image": getattr(self.app, "logo_in_memory", None),
            "signature_path": None
        }
        if getattr(self.app, "signature_image", None):
            inv["signature_image"] = self.app.signature_image.copy()
        else:
            inv["signature_image"] = None
        inv["due_date"] = self.due_ent.get_date().isoformat() if hasattr(self.due_ent, "get_date") else self.due_ent.get().strip()
        return inv

    def save_invoice_fullwidth(self):
        """
        If editing_base is set, overwrite files with that base name.
        Otherwise save as new named by invoice_number field.
        """
        if not self.app.items:
            if not messagebox.askyesno("No items", "There are no items. Save anyway?"):
                return
        inv = self.build_invoice_data()

        # choose filename base: editing mode or new
        if getattr(self, "editing_base", None):
            safe = self.editing_base
        else:
            base = inv.get("invoice_number") or f"inv-{date.today().isoformat()}"
            safe = "".join(c for c in base if c.isalnum() or c in "-_")
            if not safe:
                safe = f"invoice-{date.today().isoformat()}"

        pdf_fn = os.path.join(self.app.invoices_folder, safe + ".pdf")
        json_fn = os.path.join(self.app.invoices_folder, safe + ".json")

        try:
            make_invoice(pdf_fn, inv)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create PDF:\n{e}")
            return

        # write metadata (without in-memory images)
        safe_inv = dict(inv)
        safe_inv.pop("signature_image", None)
        safe_inv.pop("logo_image", None)
        if getattr(self.app, "signature_image", None) and not safe_inv.get("signature_path"):
            safe_inv["signature_saved_in_pdf_only"] = True

        try:
            with open(json_fn, "w", encoding="utf-8") as f:
                json.dump(safe_inv, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showwarning("Warning", f"PDF saved but failed to save JSON metadata:\n{e}")
            return

        # If we were editing an existing invoice, keep editing_base until user clears or creates new
        messagebox.showinfo("Saved", f"Saved PDF:\n{pdf_fn}\n\nSaved JSON:\n{json_fn}")
        self.app.load_receipts_list()
        self.app.load_reports_table()
        try:
            # If not editing, increment invoice number for next new invoice
            if not getattr(self, "editing_base", None):
                self.app.set_next_invoice_number()
        except Exception:
            pass

    # ---------- load invoice data into page for editing ----------
    def load_invoice_data(self, inv_data: dict, editing_base: str = None):
        """
        Populate the invoice page controls with data from inv_data (a dict).
        Set self.editing_base to the base filename (without extension) to ensure
        save overwrites the same files.
        """
        try:
            self.editing_base = editing_base
            # Company / address
            comp_addr = inv_data.get("company_address", "") or inv_data.get("company_name", "")
            self.from_txt.delete("1.0", tk.END)
            self.from_txt.insert("1.0", comp_addr)

            # invoice number (keep original)
            inv_no = inv_data.get("invoice_number", "") or (editing_base or "")
            self.inv_ent.delete(0, tk.END)
            self.inv_ent.insert(0, str(inv_no))

            # dates and contact
            try:
                if inv_data.get("date"):
                    self.date_ent.set_date(inv_data.get("date"))
                else:
                    self.date_ent.set_date(date.today())
            except Exception:
                try:
                    self.date_ent.set_date(date.today())
                except Exception:
                    pass
            try:
                if inv_data.get("due_date"):
                    self.due_ent.set_date(inv_data.get("due_date"))
                else:
                    self.due_ent.set_date(date.today() + timedelta(days=15))
            except Exception:
                try:
                    self.due_ent.set_date(date.today() + timedelta(days=15))
                except Exception:
                    pass

            self.contact_ent.delete(0, tk.END)
            self.contact_ent.insert(0, inv_data.get("bill_to", {}).get("contact", ""))

            # bill to / items / tax / discount / notes
            bill_name = inv_data.get("bill_to", {}).get("name", "")
            self.bill_txt.delete("1.0", tk.END)
            self.bill_txt.insert("1.0", bill_name)

            # items: clear tree and app.items then populate
            self.tree.delete(*self.tree.get_children())
            self.app.items = []
            for it in inv_data.get("items", []):
                # normalize fields
                try:
                    qty = float(it.get("qty", 0))
                except Exception:
                    qty = 0.0
                try:
                    unitp = float(it.get("unit_price", it.get("unit", 0) or 0))
                except Exception:
                    unitp = 0.0
                desc = it.get("desc", "") or it.get("description", "")
                item = {"desc": desc, "qty": qty, "unit_price": unitp}
                self.app.items.append(item)
                amt = qty * unitp
                qty_display = str(int(qty) if float(qty).is_integer() else qty)
                self.tree.insert("", "end", values=("✖", desc, qty_display, f"{unitp:.2f}", f"{amt:.2f}"))

            # tax/discount/notes
            try:
                self.tax_ent.delete(0, tk.END)
                self.tax_ent.insert(0, str(inv_data.get("tax_rate", inv_data.get("tax_percent", 0.0)) or 0.0))
            except Exception:
                pass
            try:
                self.disc_ent.delete(0, tk.END)
                self.disc_ent.insert(0, str(inv_data.get("discount", 0.0) or 0.0))
            except Exception:
                pass
            self.terms_txt.delete("1.0", tk.END)
            self.terms_txt.insert("1.0", inv_data.get("notes", ""))

            # logo: try logo_path from json if present
            self.app.logo_path = inv_data.get("logo_path", None)
            self.app.logo_in_memory = None
            if self.app.logo_path and os.path.exists(self.app.logo_path):
                try:
                    pil = Image.open(self.app.logo_path)
                    self.app.logo_in_memory = pil_trim_whitespace(pil)
                except Exception:
                    self.app.logo_in_memory = None
            self.update_logo_preview()

            # signature: if json contained a signature_path we can load it
            sig_path = inv_data.get("signature_path", None)
            self.app.signature_image = None
            if sig_path and os.path.exists(sig_path):
                try:
                    sig_img = Image.open(sig_path).convert("RGB")
                    self.app.signature_image = sig_img
                except Exception:
                    self.app.signature_image = None
            # if signature_saved_in_pdf_only is present we can't extract it here
            self.update_signature_preview()

            # totals update
            self.app.update_totals()
        except Exception as e:
            messagebox.showerror("Load Invoice Failed", f"Failed to load invoice data:\n{e}")

    def clear_form(self):
        """Reset form to a fresh, empty invoice (clears editing state)."""
        try:
            self.editing_base = None
            self.from_txt.delete("1.0", tk.END)
            self.from_txt.insert("1.0", "Your Company Name\nAddress line 1\nAddress line 2")

            self.bill_txt.delete("1.0", tk.END)
            self.bill_txt.insert("1.0", "Customer Name")

            self.inv_ent.delete(0, tk.END)
            # invoice number will be set by caller (set_next_invoice_number)

            self.date_ent.set_date(date.today())
            self.due_ent.set_date(date.today() + timedelta(days=15))
            self.contact_ent.delete(0, tk.END)

            self.tree.delete(*self.tree.get_children())
            self.app.items = []

            self.tax_ent.delete(0, tk.END); self.tax_ent.insert(0, "0.00")
            self.disc_ent.delete(0, tk.END); self.disc_ent.insert(0, "0.00")
            self.terms_txt.delete("1.0", tk.END); self.terms_txt.insert("1.0", "Payment is due within 15 days")

            # clear images
            self.app.logo_path = None; self.app.logo_in_memory = None; self.logo_thumbnail = None
            try:
                self.logo_canvas.delete("all")
                self.logo_canvas.create_text(60, 30, text="No logo", fill="#777")
            except Exception:
                pass

            self.app.signature_image = None; self.app.signature_thumbnail = None
            self.sig_preview_label.configure(text="No signature", image="")

            self.app.update_totals()
        except Exception as ex:
            print("clear_form failed:", ex)

class ReceiptsPage(ttk.Frame):
    def __init__(self, parent, app: SidebarApp):
        super().__init__(parent)
        self.app = app
        top = ttk.Frame(self, padding=8); top.pack(fill=tk.X)
        ttk.Label(top, text="Saved PDFs", font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)
        btn_frame = ttk.Frame(top); btn_frame.pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Refresh", command=self.app.load_receipts_list).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Open Selected", command=self.app.open_selected_receipt).pack(side=tk.RIGHT, padx=6)
        ttk.Button(btn_frame, text="Edit Selected", command=self.app.edit_selected_receipt).pack(side=tk.RIGHT, padx=6)
        ttk.Button(btn_frame, text="Delete Selected", command=self.app.delete_selected_receipt).pack(side=tk.RIGHT, padx=(6,0))
        ttk.Button(btn_frame, text="Undo Delete", command=self.app.undo_delete).pack(side=tk.RIGHT, padx=(6,0))
        self.app.receipts_listbox = tk.Listbox(self)
        self.app.receipts_listbox.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

class ReportsPage(ttk.Frame):
    def __init__(self, parent, app: SidebarApp):
        super().__init__(parent)
        self.app = app
        top = ttk.Frame(self, padding=8); top.pack(fill=tk.X)
        ttk.Label(top, text="Invoice Reports", font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(top, text="Refresh", command=self.app.load_reports_table).pack(side=tk.RIGHT)
        ttk.Button(top, text="Export CSV", command=self.app.export_reports_csv).pack(side=tk.RIGHT, padx=6)
        ttk.Button(top, text="Open PDF", command=self.app.open_pdf_from_report).pack(side=tk.RIGHT, padx=6)

        cols = ("customer","invoice","date","due_date","contact","tax_pct","discount","subtotal","tax_amt","total")
        self.app.reports_tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        headings = {"customer":"Customer","invoice":"Invoice No","date":"Date","due_date":"Due Date","contact":"Contact",
                    "tax_pct":"Tax %","discount":"Discount","subtotal":"Subtotal","tax_amt":"Tax Amt","total":"Total"}
        for c in cols:
            self.app.reports_tree.heading(c, text=headings[c])
            if c == "customer":
                self.app.reports_tree.column(c, width=220)
            elif c == "invoice":
                self.app.reports_tree.column(c, width=80, anchor=tk.CENTER)
            else:
                self.app.reports_tree.column(c, width=90, anchor=tk.CENTER)
        self.app.reports_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
        self.app.reports_tree.bind("<Double-1>", lambda e: self.app.open_pdf_from_report())

# ---------- Signature canvas & AddItemDialog ----------
class SignatureCanvas(tk.Toplevel):
    def __init__(self, parent, width=600, height=180, bg="white"):
        super().__init__(parent)
        self.title("Sign here")
        self.resizable(False, False)
        self.canvas_width = width; self.canvas_height = height; self.bg = bg
        self.image = Image.new("RGB", (width, height), bg)
        self.draw = ImageDraw.Draw(self.image)
        self.canvas = tk.Canvas(self, width=width, height=height, bg=bg, cursor="cross"); self.canvas.pack()
        btn_frame = ttk.Frame(self); btn_frame.pack(fill=tk.X, pady=4)
        ttk.Button(btn_frame, text="Clear", command=self.clear).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Save & Close", command=self.save_and_close).pack(side=tk.RIGHT, padx=4)
        self.old_x = None; self.old_y = None; self.pen_width = 2; self.pen_fill = "black"
        self.canvas.bind("<ButtonPress-1>", self.pen_down)
        self.canvas.bind("<B1-Motion>", self.pen_move)
        self.canvas.bind("<ButtonRelease-1>", self.pen_up)
        self.result_image = None

    def pen_down(self, event): self.old_x = event.x; self.old_y = event.y
    def pen_move(self, event):
        if self.old_x is not None and self.old_y is not None:
            x, y = event.x, event.y
            self.canvas.create_line(self.old_x, self.old_y, x, y, width=self.pen_width, fill=self.pen_fill, capstyle=tk.ROUND, smooth=True)
            self.draw.line([(self.old_x, self.old_y), (x, y)], fill=self.pen_fill, width=self.pen_width)
            self.old_x = x; self.old_y = y
    def pen_up(self, event): self.old_x = None; self.old_y = None
    def clear(self):
        self.canvas.delete("all"); self.image = Image.new("RGB", (self.canvas_width, self.canvas_height), self.bg); self.draw = ImageDraw.Draw(self.image)
    def save_and_close(self): self.result_image = self.image.copy(); self.destroy()

class AddItemDialog(simpledialog.Dialog):
    def body(self, master):
        ttk.Label(master, text="Description:").grid(row=0, column=0, sticky=tk.W)
        self.desc = ttk.Entry(master, width=50); self.desc.grid(row=0, column=1, padx=4, pady=2)
        ttk.Label(master, text="Qty:").grid(row=1, column=0, sticky=tk.W)
        self.qty = ttk.Entry(master, width=10); self.qty.grid(row=1, column=1, sticky=tk.W, padx=4, pady=2); self.qty.insert(0, "1")
        ttk.Label(master, text="Unit Price:").grid(row=2, column=0, sticky=tk.W)
        self.unit = ttk.Entry(master, width=15); self.unit.grid(row=2, column=1, sticky=tk.W, padx=4, pady=2); self.unit.insert(0, "0.00")
        return self.desc
    def apply(self):
        try:
            qty = float(self.qty.get()); unit = float(self.unit.get()); desc = self.desc.get().strip()
            if not desc: raise ValueError("Description empty")
            self.result = {"desc": desc, "qty": qty, "unit_price": unit}
        except Exception as e:
            messagebox.showerror("Invalid", f"Invalid item: {e}"); self.result = None

# ---------- Run ----------
if __name__ == "__main__":
    app = SidebarApp()
    app.mainloop()
