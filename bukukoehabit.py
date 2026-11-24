"""
BukuKoe - Aplikasi track habit membaca buku
Python + customtkinter + MySQL

Instalasi  : pip install customtkinter mysql-connector-python
Menjalankan: python bukukoe.py

Konfigurasi MySQL: ubah DB_CONFIG di bawah, atau pakai environment variable
BUKUKOE_DB_HOST, BUKUKOE_DB_PORT, BUKUKOE_DB_USER, BUKUKOE_DB_PASSWORD, BUKUKOE_DB_NAME.
Database dan tabel dibuat otomatis jika belum ada.
"""

import hashlib
import hmac
import os
import sys
import tkinter as tk
from datetime import datetime

import customtkinter as ctk
import mysql.connector

# ----------------------------------------------------------------- TEMA
BG = "#D9D9D9"
PANEL = "#C9D1DB"
PANEL_LIGHT = "#E4E9F0"
DIALOG_BG = "#B3B3B3"
BTN = "#D9D9D9"
BTN_HOVER = "#C4C4C4"
BLUE = "#4C7FF8"
GREEN = "#3BA55D"
TRACK = "#DDE3EC"
BLACK = "#000000"
WHITE = "#FFFFFF"
FONT = "Open Sans"  # jika tidak ada, tkinter memakai font default

DB_CONFIG = {
    "host": os.environ.get("BUKUKOE_DB_HOST", "localhost"),
    "port": int(os.environ.get("BUKUKOE_DB_PORT", "3306")),
    "user": os.environ.get("BUKUKOE_DB_USER", "root"),
    "password": os.environ.get("BUKUKOE_DB_PASSWORD", ""),
}
DB_NAME = os.environ.get("BUKUKOE_DB_NAME", "bukukoe")


def font(size=13, bold=True):
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")


# ----------------------------------------------------------------- DATA
class Store:
    """Penyimpanan MySQL. Data buku dipisah per user."""

    def __init__(self):
        boot = mysql.connector.connect(**DB_CONFIG)
        cur = boot.cursor()
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        boot.commit()
        cur.close()
        boot.close()

        self.conn = mysql.connector.connect(database=DB_NAME, charset="utf8mb4", **DB_CONFIG)
        self.last_id = None
        self._exec(
            """CREATE TABLE IF NOT EXISTS users(
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL UNIQUE,
                salt VARBINARY(16) NOT NULL,
                pw_hash VARBINARY(32) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
        )
        self._exec(
            """CREATE TABLE IF NOT EXISTS books(
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                title VARCHAR(255) NOT NULL,
                author VARCHAR(255) NOT NULL,
                total_pages INT NOT NULL,
                pages_read INT NOT NULL DEFAULT 0,
                summary TEXT NOT NULL,
                target VARCHAR(10) NOT NULL DEFAULT '',
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
        )

    def _exec(self, sql, params=(), fetch=None):
        """Jalankan query: auto reconnect + auto commit."""
        self.conn.ping(reconnect=True, attempts=3, delay=1)
        cur = self.conn.cursor(dictionary=True)
        try:
            cur.execute(sql, params)
            result = None
            if fetch == "one":
                result = cur.fetchone()
            elif fetch == "all":
                result = cur.fetchall()
            self.conn.commit()
            self.last_id = cur.lastrowid
            return result
        finally:
            cur.close()

    # ---- user
    @staticmethod
    def _hash(password, salt):
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes(salt), 120_000)

    def register(self, username, password):
        salt = os.urandom(16)
        try:
            self._exec("INSERT INTO users(username, salt, pw_hash) VALUES(%s,%s,%s)",
                       (username, salt, self._hash(password, salt)))
            return True
        except mysql.connector.IntegrityError:
            return False

    def login(self, username, password):
        """Mengembalikan id user, atau None jika gagal."""
        row = self._exec("SELECT * FROM users WHERE username=%s", (username,), fetch="one")
        if row and hmac.compare_digest(bytes(row["pw_hash"]), self._hash(password, row["salt"])):
            return row["id"]
        return None

    # ---- buku
    def books(self, user_id):
        return self._exec("SELECT * FROM books WHERE user_id=%s ORDER BY id", (user_id,), fetch="all")

    def add_book(self, user_id, title, author, total):
        self._exec("INSERT INTO books(user_id,title,author,total_pages,summary) VALUES(%s,%s,%s,%s,'')",
                   (user_id, title, author, total))
        return self.last_id

    def update_book(self, book_id, title, author, total, read, target):
        self._exec("""UPDATE books SET title=%s, author=%s, total_pages=%s, pages_read=%s, target=%s
                      WHERE id=%s""", (title, author, total, read, target, book_id))

    def update_progress(self, book_id, pages_read):
        self._exec("UPDATE books SET pages_read=%s WHERE id=%s", (pages_read, book_id))

    def save_summary(self, book_id, summary):
        self._exec("UPDATE books SET summary=%s WHERE id=%s", (summary, book_id))

    def delete_book(self, book_id):
        self._exec("DELETE FROM books WHERE id=%s", (book_id,))


def is_done(b):
    return b["total_pages"] > 0 and b["pages_read"] >= b["total_pages"]


def percent(b):
    return min(100, b["pages_read"] * 100 / b["total_pages"]) if b["total_pages"] > 0 else 0


#  DIALOG
class Dialog(ctk.CTkToplevel):
    """Popup abu-abu (modal), muncul di tengah jendela induk."""

    def __init__(self, master, title="", width=420, height=300):
        super().__init__(master, fg_color=DIALOG_BG)
        self.title(title)
        self.parent_top = master.winfo_toplevel()
        root = self.parent_top
        x = root.winfo_x() + (root.winfo_width() - width) // 2
        y = root.winfo_y() + (root.winfo_height() - height) // 2
        self.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")
        self.resizable(False, False)
        self.transient(root)
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(120, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except Exception:
            pass

    def destroy(self):
        parent = self.parent_top
        super().destroy()
        if isinstance(parent, Dialog):  # kembalikan modal ke dialog induk
            try:
                parent.after(50, parent._grab)
            except Exception:
                pass


def info_dialog(master, text):
    d = Dialog(master, "Info", 380, 190)
    ctk.CTkLabel(d, text=text, font=font(13), wraplength=320).pack(pady=(40, 20), padx=20)
    small_btn(d, "OK", d.destroy, width=90).pack()


def confirm_dialog(master, text, on_yes):
    d = Dialog(master, "Konfirmasi", 420, 210)
    ctk.CTkLabel(d, text=text, font=font(15), wraplength=360).pack(pady=(40, 25), padx=20)
    row = ctk.CTkFrame(d, fg_color="transparent")
    row.pack()

    def yes():
        d.destroy()
        on_yes()

    small_btn(row, "YA", yes, width=120).pack(side="left", padx=15)
    small_btn(row, "TIDAK", d.destroy, width=120).pack(side="left", padx=15)


def pill_entry(master, placeholder="", **kw):
    return ctk.CTkEntry(master, placeholder_text=placeholder, height=34, corner_radius=17,
                        fg_color=BTN, border_width=0, text_color=BLACK, font=font(12, False), **kw)


def small_btn(master, text, command, width=130):
    return ctk.CTkButton(master, text=text, width=width, height=30, fg_color=BTN,
                         text_color=BLACK, hover_color=BTN_HOVER, corner_radius=8,
                         border_width=1, border_color="#333333", font=font(12), command=command)


#  HALAMAN DASAR
class Page(ctk.CTkFrame):
    def __init__(self, app):
        super().__init__(app, fg_color=BG, corner_radius=0)
        self.app = app
        self.store = app.store


#  1. LOGIN
class LoginPage(Page):
    def __init__(self, app):
        super().__init__(app)
        card = ctk.CTkFrame(self, fg_color=DIALOG_BG, corner_radius=28, width=330, height=300)
        card.place(relx=0.5, rely=0.5, anchor="center")
        card.pack_propagate(False)

        ctk.CTkLabel(card, text="BukuKoe", font=font(28)).pack(pady=(26, 14))
        self.user = pill_entry(card, "Username", width=230)
        self.user.pack(pady=6)
        self.pw = pill_entry(card, "Password", width=230, show="*")
        self.pw.pack(pady=6)
        self.pw.bind("<Return>", lambda e: self.do_login())

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(pady=24)
        small_btn(row, "Login", self.do_login, width=90).pack(side="left", padx=10)
        small_btn(row, "Daftar", self.do_register, width=90).pack(side="left", padx=10)
        self.user.focus()

    def do_login(self):
        u, p = self.user.get().strip(), self.pw.get()
        if not u or not p:
            return info_dialog(self, "Username dan password wajib diisi.")
        uid = self.store.login(u, p)
        if uid is None:
            return info_dialog(self, "Username atau password salah.")
        self.app.user_id = uid
        self.app.username = u
        self.app.show("main")

    def do_register(self):
        u, p = self.user.get().strip(), self.pw.get()
        if len(u) < 3 or len(p) < 4:
            return info_dialog(self, "Username minimal 3 karakter dan password minimal 4 karakter "
                                     "(isi kedua kolom lalu tekan Daftar).")
        if self.store.register(u, p):
            info_dialog(self, "Akun berhasil dibuat. Silakan login.")
        else:
            info_dialog(self, "Username sudah dipakai.")


#  2. HALAMAN UTAMA
class MainPage(Page):
    def __init__(self, app):
        super().__init__(app)
        self.books = []
        self.selected_id = None
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.build_sidebar()
        tk.Frame(self, bg="#111111", width=3).grid(row=0, column=1, sticky="ns")
        self.build_content()
        self.refresh()

    # - layout
    def build_sidebar(self):
        side = ctk.CTkFrame(self, fg_color=BG, corner_radius=0, width=210)
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_propagate(False)
        side.grid_rowconfigure(3, weight=1)
        side.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(side, fg_color="transparent")
        top.grid(row=0, column=0, sticky="w", padx=10, pady=(14, 6))
        self.btn_plus = ctk.CTkButton(top, text="+", width=46, height=30, fg_color="#B3B3B3",
                                      hover_color="#9E9E9E", text_color=BLACK, font=font(18),
                                      command=self.plus_menu)
        self.btn_plus.pack(side="left", padx=(0, 8))
        ctk.CTkButton(top, text="-", width=46, height=30, fg_color="#B3B3B3",
                      hover_color="#9E9E9E", text_color=BLACK, font=font(18),
                      command=self.delete_form).pack(side="left")

        ctk.CTkLabel(side, text="Nama Buku", font=font(13), anchor="w").grid(
            row=1, column=0, sticky="w", padx=14, pady=(8, 2))
        self.side_list = ctk.CTkScrollableFrame(side, fg_color="transparent", height=170, corner_radius=0)
        self.side_list.grid(row=2, column=0, sticky="ew", padx=4)

        prog = ctk.CTkFrame(side, fg_color="transparent")
        prog.grid(row=3, column=0, sticky="nw", padx=14, pady=(14, 0))
        ctk.CTkLabel(prog, text="Progress", font=font(13)).pack(anchor="w")
        self.lb_title = ctk.CTkLabel(prog, text="", font=font(12, False), anchor="w",
                                     justify="left", wraplength=180)
        self.lb_title.pack(anchor="w", pady=(6, 0))
        self.lb_pages = ctk.CTkLabel(prog, text="", font=font(12, False), anchor="w")
        self.lb_pages.pack(anchor="w")
        self.lb_done = ctk.CTkLabel(prog, text="", font=font(12, False), anchor="w")
        self.lb_done.pack(anchor="w")
        self.lb_target = ctk.CTkLabel(prog, text="", font=font(12, False), anchor="w",
                                      justify="left", wraplength=180)
        self.lb_target.pack(anchor="w", pady=(24, 0))

        # tombol tambah / kurangi halaman yang dibaca
        pbtn = ctk.CTkFrame(prog, fg_color="transparent")
        pbtn.pack(anchor="w", pady=(8, 0))
        ctk.CTkButton(pbtn, text="+", width=46, height=30, fg_color="#B3B3B3",
                      hover_color="#9E9E9E", text_color=BLACK, font=font(18),
                      command=lambda: self.progress_form(+1)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(pbtn, text="-", width=46, height=30, fg_color="#B3B3B3",
                      hover_color="#9E9E9E", text_color=BLACK, font=font(18),
                      command=lambda: self.progress_form(-1)).pack(side="left")
        ctk.CTkLabel(prog, text="+/- halaman dibaca", font=font(10, False),
                     text_color="#555555").pack(anchor="w", pady=(2, 0))

        bottom = ctk.CTkFrame(side, fg_color="transparent")
        bottom.grid(row=4, column=0, sticky="ew", padx=14, pady=12)
        ctk.CTkLabel(bottom, text="BukuKoe", font=font(14)).pack(side="left")
        ctk.CTkButton(bottom, text="Keluar", width=60, height=24, fg_color=BTN, hover_color=BTN_HOVER,
                      text_color=BLACK, font=font(11), command=lambda: self.app.show("login")
                      ).pack(side="right")

    def build_content(self):
        content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        content.grid(row=0, column=2, sticky="nsew", padx=10, pady=10)
        content.grid_columnconfigure((0, 1), weight=2, uniform="a")
        content.grid_columnconfigure(2, weight=3, uniform="a")
        content.grid_rowconfigure(0, weight=2, uniform="r")
        content.grid_rowconfigure(1, weight=3, uniform="r")

        # Daftar Buku
        card = ctk.CTkFrame(content, fg_color=PANEL, corner_radius=12)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 6))
        ctk.CTkLabel(card, text="Daftar Buku", font=font(13)).pack(pady=(10, 2))
        self.list_scroll = ctk.CTkScrollableFrame(card, fg_color="transparent")
        self.list_scroll.pack(fill="both", expand=True, padx=6, pady=(0, 8))

        # Ringkasan
        card = ctk.CTkFrame(content, fg_color=PANEL, corner_radius=12)
        card.grid(row=0, column=1, sticky="nsew", padx=(0, 6), pady=(0, 6))
        ctk.CTkLabel(card, text="Ringkasan", font=font(13)).pack(pady=(10, 0))
        self.lb_sum_book = ctk.CTkLabel(card, text="", font=font(11, False), text_color="#333333",
                                        wraplength=200)
        self.lb_sum_book.pack()
        self.txt_sum = ctk.CTkTextbox(card, fg_color=PANEL_LIGHT, text_color=BLACK,
                                      corner_radius=8, height=60)
        self.txt_sum.pack(fill="both", expand=True, padx=10, pady=(4, 4))
        self.btn_sum = small_btn(card, "Simpan Ringkasan", self.save_summary, width=150)
        self.btn_sum.pack(pady=(0, 8))

        # Progress Membaca
        card = ctk.CTkFrame(content, fg_color=PANEL, corner_radius=12)
        card.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(card, text="Progress Membaca", font=font(18, False)).pack(pady=(10, 0))
        self.bar_canvas = tk.Canvas(card, bg=PANEL, highlightthickness=0)
        self.bar_canvas.pack(fill="both", expand=True, padx=12, pady=10)
        self.bar_canvas.bind("<Configure>", lambda e: self.draw_bars())

        # Buku Selesai (donat)
        card = ctk.CTkFrame(content, fg_color=PANEL, corner_radius=12)
        card.grid(row=0, column=2, rowspan=2, sticky="nsew")
        self.donut_canvas = tk.Canvas(card, bg=PANEL, highlightthickness=0)
        self.donut_canvas.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        self.donut_canvas.bind("<Configure>", lambda e: self.draw_donut())
        ctk.CTkLabel(card, text="Buku\nSelesai", font=font(20)).pack(pady=(0, 4))
        self.lb_donut = ctk.CTkLabel(card, text="", font=font(12, False), text_color="#333333")
        self.lb_donut.pack(pady=(0, 14))

    # - data & tampilan
    def current(self):
        return next((b for b in self.books if b["id"] == self.selected_id), None)

    def select(self, book_id):
        self.selected_id = book_id
        self.refresh()

    def refresh(self):
        self.books = self.store.books(self.app.user_id)
        if self.current() is None:
            self.selected_id = self.books[0]["id"] if self.books else None
        self.fill_sidebar()
        self.fill_list()
        self.fill_summary()
        self.draw_bars()
        self.draw_donut()

    def fill_sidebar(self):
        for w in self.side_list.winfo_children():
            w.destroy()
        if not self.books:
            ctk.CTkLabel(self.side_list, text="Belum ada buku", font=font(11, False),
                         text_color="#555555").pack(anchor="w", padx=8)
        for b in self.books:
            active = b["id"] == self.selected_id
            ctk.CTkButton(self.side_list, text=b["title"], anchor="w", height=26,
                          fg_color="#B3B3B3" if active else "transparent", hover_color=BTN_HOVER,
                          text_color=BLACK, font=font(12, False),
                          command=lambda i=b["id"]: self.select(i)).pack(fill="x", pady=1)
        cur = self.current()
        done = sum(1 for b in self.books if is_done(b))
        self.lb_title.configure(text=f"Buku (judul): {cur['title']}" if cur else "Buku (judul): -")
        self.lb_pages.configure(text=f"Halaman: {cur['pages_read']}/{cur['total_pages']}" if cur else "Halaman: -")
        self.lb_done.configure(text=f"Selesai: {done}/{len(self.books)}")
        self.lb_target.configure(text=f"Target selesai: {cur['target'] or '-'}" if cur else "Target selesai: -")

    def fill_list(self):
        for w in self.list_scroll.winfo_children():
            w.destroy()
        reading = [b for b in self.books if not is_done(b)]
        if not reading:
            ctk.CTkLabel(self.list_scroll, text="Tidak ada buku yang sedang dibaca",
                         font=font(11, False), text_color="#555555").pack(pady=10)
        for b in reading:
            ctk.CTkButton(self.list_scroll, anchor="w", height=36,
                          text=f"{b['title']}\n{b['author']}  •  {percent(b):.0f}%",
                          fg_color=PANEL_LIGHT, hover_color="#D5DCE6", text_color=BLACK,
                          font=font(11, False),
                          command=lambda i=b["id"]: self.select(i)).pack(fill="x", pady=2)

    def fill_summary(self):
        cur = self.current()
        self.txt_sum.configure(state="normal")
        self.txt_sum.delete("1.0", "end")
        if cur:
            self.lb_sum_book.configure(text=f"{cur['title']} — {cur['author']}")
            self.txt_sum.insert("1.0", cur["summary"])
            self.btn_sum.configure(state="normal")
        else:
            self.lb_sum_book.configure(text="Tambah buku dulu dengan tombol +")
            self.txt_sum.configure(state="disabled")
            self.btn_sum.configure(state="disabled")

    def save_summary(self):
        cur = self.current()
        if cur:
            self.store.save_summary(cur["id"], self.txt_sum.get("1.0", "end").strip())
            self.books = self.store.books(self.app.user_id)
            info_dialog(self, "Ringkasan tersimpan.")

    # ---------------- diagram
    def draw_bars(self):
        c = self.bar_canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 50 or h < 50:
            return
        if not self.books:
            for y0, bw in ((0.25, 0.45), (0.40, 0.25), (0.62, 0.20), (0.74, 0.12)):
                c.create_rectangle(w * 0.3, h * y0, w * (0.3 + bw), h * y0 + 14, fill="#A6AAB0", outline="")
            c.create_rectangle(w / 2 - 130, h / 2 - 30, w / 2 + 130, h / 2 + 30, fill="#F4F5F7", outline="")
            c.create_text(w / 2, h / 2, text="Tidak ada data yang ditampilkan", font=(FONT, 12), fill=BLACK)
            return

        reading = [b for b in self.books if not is_done(b)]
        done = [b for b in self.books if is_done(b)]
        x0, x1, row_h = 154, w - 50, 24
        max_rows = max(1, int((h - 60) / row_h / 2))

        def section(y, header, items, color):
            c.create_text(6, y, anchor="nw", text=header, font=(FONT, 11, "bold"), fill=BLACK)
            y += 22
            if not items:
                c.create_text(14, y, anchor="nw", text="-", font=(FONT, 11), fill="#555555")
                return y + row_h
            for b in items[:max_rows]:
                t = b["title"] if len(b["title"]) <= 20 else b["title"][:19] + "…"
                c.create_text(6, y + 8, anchor="w", text=t, font=(FONT, 10), fill=BLACK)
                c.create_rectangle(x0, y, x1, y + 16, fill=TRACK, outline="")
                p = percent(b)
                if p > 0:
                    c.create_rectangle(x0, y, x0 + (x1 - x0) * p / 100, y + 16, fill=color, outline="")
                c.create_text(x1 + 6, y + 8, anchor="w", text=f"{p:.0f}%", font=(FONT, 10), fill=BLACK)
                y += row_h
            if len(items) > max_rows:
                c.create_text(6, y, anchor="nw", text=f"+{len(items) - max_rows} buku lainnya",
                              font=(FONT, 9), fill="#555555")
                y += 16
            return y

        y = section(4, "Sedang dibaca (belum selesai)", reading, BLUE)
        section(y + 6, "Sudah selesai dibaca", done, GREEN)

    def draw_donut(self):
        c = self.donut_canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 60 or h < 60:
            return
        total = len(self.books)
        finished = sum(1 for b in self.books if is_done(b))
        pct = finished * 100 / total if total else 0

        size = min(w, h) - 30
        thick = max(24, size * 0.17)
        x0, y0 = (w - size) / 2 + thick / 2, (h - size) / 2 + thick / 2
        x1, y1 = (w + size) / 2 - thick / 2, (h + size) / 2 - thick / 2
        if pct <= 0 or pct >= 100:
            c.create_oval(x0, y0, x1, y1, outline=BLUE, width=thick)  # 0% tetap biru seperti mockup
        else:
            c.create_oval(x0, y0, x1, y1, outline=TRACK, width=thick)
            c.create_arc(x0, y0, x1, y1, start=90, extent=-pct * 3.6, style="arc", outline=BLUE, width=thick)
        c.create_text(w / 2, h / 2, text=f"{pct:.0f}%", fill=BLACK, font=(FONT, int(size * 0.18)))
        self.lb_donut.configure(text=f"{finished} dari {total} buku")

    # ---------------- menu + / -
    def plus_menu(self):
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Tambah Buku", command=self.add_form)
        m.add_command(label="Update Buku", command=self.update_form)
        m.tk_popup(self.btn_plus.winfo_rootx(), self.btn_plus.winfo_rooty() + self.btn_plus.winfo_height())

    # ---------------- form tambah / update / hapus
    def _book_form(self, mode, book=None):
        titles = {"add": "Tambah Buku", "update": "Update Buku", "delete": "Hapus Buku"}
        btn_text = {"add": "Tambah", "update": "Update", "delete": "Hapus"}[mode]
        height = {"add": 470, "update": 620, "delete": 380}[mode]
        d = Dialog(self, titles[mode], 460, height)
        ctk.CTkLabel(d, text=titles[mode].replace(" ", "\n"), font=font(20)).pack(pady=(18, 4))

        body = ctk.CTkFrame(d, fg_color="transparent")
        body.pack(fill="x", padx=30)
        fields = [("title", "Judul Buku"), ("author", "Penulis")]
        if mode != "delete":
            fields.append(("total", "Halaman (total halaman buku)"))
        if mode == "update":
            fields += [("read", "Halaman yang sudah dibaca"), ("target", "Target selesai (YYYY-MM-DD)")]
        e = {}
        for key, text in fields:
            ctk.CTkLabel(body, text=text, font=font(13), anchor="w").pack(fill="x", pady=(8, 2))
            e[key] = pill_entry(body, width=400)
            e[key].pack(fill="x")

        if book is not None:
            e["title"].insert(0, book["title"])
            e["author"].insert(0, book["author"])
            if mode == "update":
                e["total"].insert(0, str(book["total_pages"]))
                e["read"].insert(0, str(book["pages_read"]))
                e["target"].insert(0, book["target"])

        def to_int(s):
            try:
                return int(s)
            except ValueError:
                return None

        def submit():
            v = {k: w.get().strip() for k, w in e.items()}
            if not v["title"] or not v["author"]:
                return info_dialog(d, "Judul buku dan penulis wajib diisi.")

            if mode == "delete":
                match = next((b for b in self.books if b["title"].lower() == v["title"].lower()
                              and b["author"].lower() == v["author"].lower()), None)
                if not match:
                    return info_dialog(d, "Buku dengan judul dan penulis tersebut tidak ditemukan.")

                def go():
                    self.store.delete_book(match["id"])
                    d.destroy()
                    self.refresh()
                return confirm_dialog(d, f"Apakah anda yakin ingin menghapus \"{match['title']}\" ?", go)

            total = to_int(v["total"])
            if total is None or total <= 0:
                return info_dialog(d, "Halaman harus berupa angka lebih dari 0.")

            if mode == "add":
                self.selected_id = self.store.add_book(self.app.user_id, v["title"], v["author"], total)
            else:
                read = to_int(v["read"] or "0")
                if read is None or read < 0 or read > total:
                    return info_dialog(d, "Halaman yang dibaca harus antara 0 dan total halaman.")
                if v["target"]:
                    try:
                        datetime.strptime(v["target"], "%Y-%m-%d")
                    except ValueError:
                        return info_dialog(d, "Format target harus YYYY-MM-DD (contoh 2026-12-31).")
                self.store.update_book(book["id"], v["title"], v["author"], total, read, v["target"])
            d.destroy()
            self.refresh()

        row = ctk.CTkFrame(d, fg_color="transparent")
        row.pack(fill="x", padx=30, pady=22)
        small_btn(row, btn_text, submit, width=130).pack(side="left")
        small_btn(row, "Batal", d.destroy, width=130).pack(side="right")
        d.bind("<Return>", lambda ev: submit())

    def progress_form(self, sign):
        """sign = +1 menambah halaman dibaca, -1 mengurangi."""
        cur = self.current()
        if not cur:
            return info_dialog(self, "Pilih atau tambah buku dulu.")
        adding = sign > 0
        title = "Tambah Halaman Dibaca" if adding else "Kurangi Halaman Dibaca"
        d = Dialog(self, title, 420, 300)
        ctk.CTkLabel(d, text=title, font=font(18)).pack(pady=(20, 4))
        ctk.CTkLabel(d, text=f"{cur['title']}\nSaat ini: {cur['pages_read']}/{cur['total_pages']} halaman",
                     font=font(12, False), wraplength=360).pack(pady=(0, 8))
        ctk.CTkLabel(d, text="Jumlah halaman", font=font(13), anchor="w").pack(fill="x", padx=30)
        e = pill_entry(d, "contoh: 10", width=360)
        e.pack(padx=30, pady=(2, 0))
        e.insert(0, "1")
        e.focus()

        def submit():
            try:
                n = int(e.get().strip())
            except ValueError:
                return info_dialog(d, "Jumlah halaman harus berupa angka.")
            if n <= 0:
                return info_dialog(d, "Jumlah halaman harus lebih dari 0.")
            new = cur["pages_read"] + sign * n
            new = max(0, min(cur["total_pages"], new))  # batas 0 .. total halaman
            self.store.update_progress(cur["id"], new)
            d.destroy()
            self.refresh()
            if adding and new >= cur["total_pages"]:
                info_dialog(self, f"Selamat! Kamu sudah menyelesaikan \"{cur['title']}\".")

        row = ctk.CTkFrame(d, fg_color="transparent")
        row.pack(fill="x", padx=30, pady=20)
        small_btn(row, "Tambah" if adding else "Kurangi", submit, width=130).pack(side="left")
        small_btn(row, "Batal", d.destroy, width=130).pack(side="right")
        d.bind("<Return>", lambda ev: submit())

    def add_form(self):
        self._book_form("add")

    def update_form(self):
        cur = self.current()
        if not cur:
            return info_dialog(self, "Belum ada buku untuk diupdate. Tambah buku dulu.")
        self._book_form("update", cur)

    def delete_form(self):
        if not self.books:
            return info_dialog(self, "Belum ada buku untuk dihapus.")
        self._book_form("delete", self.current())


# ----------------------------------------------------------------- APLIKASI
class App(ctk.CTk):
    PAGES = {"login": LoginPage, "main": MainPage}

    def __init__(self):
        super().__init__(fg_color=BG)
        ctk.set_appearance_mode("light")
        self.title("BukuKoe")
        self.geometry("1100x650")
        self.minsize(980, 600)
        try:
            self.store = Store()
        except mysql.connector.Error as err:
            info_dialog(self, f"Gagal terhubung ke MySQL:\n{err}")
            self.after(4000, self.destroy)
            self.current = None
            return
        self.user_id = None
        self.username = ""
        self.current = None
        self.show("login")

    def show(self, name):
        if self.current is not None:
            self.current.destroy()
        self.current = self.PAGES[name](self)
        self.current.pack(fill="both", expand=True)


if __name__ == "__main__":
    App().mainloop()
