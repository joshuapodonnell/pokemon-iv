import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
import csv
from pathlib import Path

DEFAULT_DB_FILE = "pokemon_ivs.db"
RANK_LIMIT_OPTIONS = [5, 10, 15, 20, 25, 50, 100]

PRESET_TEMPLATES = {
    "0/0/0 IVs (Nundos)": """SELECT id, name, cp, hp, iv_atk, iv_def, iv_sta
FROM pokemon
WHERE iv_atk = 0 AND iv_def = 0 AND iv_sta = 0;""",

    "100% IVs (Hundos)": """SELECT id, name, cp, hp, iv_atk, iv_def, iv_sta, caught_date
FROM pokemon
WHERE iv_pct = 100.0;""",

    "Top N Great League (Base)": """SELECT id, name, cp, gl_rank, gl_percentile, gl_best_cp
FROM pokemon
WHERE gl_rank <= {rank_limit}
ORDER BY gl_rank ASC;""",

    "Top N Ultra League (Base)": """SELECT id, name, cp, ul_rank, ul_percentile, ul_best_cp
FROM pokemon
WHERE ul_rank <= {rank_limit}
ORDER BY ul_rank ASC;""",

    "Rank 1 Great League (Evolutions)": """SELECT p.name AS base_pokemon, p.cp, e.evo_name, e.gl_rank, e.gl_best_cp
FROM pokemon p
JOIN evo_rankings e ON p.id = e.pokemon_id
WHERE e.gl_rank = 1;""",

    "Tagged for Transfer": """SELECT id, name, cp, iv_pct, tag
FROM pokemon
WHERE tag = 'TRANSFER' COLLATE NOCASE;""",

    "Needs Review": """SELECT id, name, cp, iv_pct, needs_review
FROM pokemon
WHERE needs_review = 1;""",

    "Custom Query (All Data)": """SELECT *
FROM pokemon
LIMIT 100;"""
}


class PokemonDBViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pokémon IV Database Viewer")
        self.geometry("1280x800")
        self.minsize(1040, 650)
        self.configure(padx=10, pady=10)

        self.db_path = tk.StringVar(value=str(Path(DEFAULT_DB_FILE).resolve()))
        self.query_var = tk.StringVar()
        self.rank_limit_var = tk.StringVar(value="10")
        self.status_var = tk.StringVar(value="Ready")
        self.last_columns = []
        self.last_rows = []

        self._build_ui()
        self.query_combo.set("0/0/0 IVs (Nundos)")
        self.on_query_select()
        self.refresh_schema()

    def _build_ui(self):
        top_frame = tk.Frame(self)
        top_frame.pack(fill=tk.X, pady=(0, 8))

        tk.Label(top_frame, text="Database:").pack(side=tk.LEFT, padx=(0, 5))
        self.db_entry = tk.Entry(top_frame, textvariable=self.db_path, width=72)
        self.db_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Button(top_frame, text="Browse...", command=self.browse_db).pack(side=tk.LEFT, padx=5)
        tk.Button(top_frame, text="Refresh Schema", command=self.refresh_schema).pack(side=tk.LEFT, padx=5)

        query_frame = tk.Frame(self)
        query_frame.pack(fill=tk.X, pady=(0, 8))

        tk.Label(query_frame, text="Preselected Queries:").pack(side=tk.LEFT, padx=(0, 5))
        self.query_combo = ttk.Combobox(
            query_frame,
            textvariable=self.query_var,
            values=list(PRESET_TEMPLATES.keys()),
            state="readonly",
            width=30,
        )
        self.query_combo.pack(side=tk.LEFT)
        self.query_combo.bind("<<ComboboxSelected>>", self.on_query_select)

        tk.Label(query_frame, text="Rank limit:").pack(side=tk.LEFT, padx=(12, 5))
        self.rank_limit_combo = ttk.Combobox(
            query_frame,
            textvariable=self.rank_limit_var,
            values=[str(x) for x in RANK_LIMIT_OPTIONS],
            state="readonly",
            width=6,
        )
        self.rank_limit_combo.pack(side=tk.LEFT)
        self.rank_limit_combo.bind("<<ComboboxSelected>>", self.on_query_select)

        tk.Button(query_frame, text="Load Preset", command=self.on_query_select).pack(side=tk.LEFT, padx=8)
        tk.Button(query_frame, text="Run Query", command=self.run_query, bg="#4CAF50").pack(side=tk.RIGHT, padx=5)
        tk.Button(query_frame, text="Export CSV", command=self.export_csv).pack(side=tk.RIGHT, padx=5)

        main_pane = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        main_pane.pack(fill=tk.BOTH, expand=True)

        left_panel = tk.Frame(main_pane)
        right_panel = tk.Frame(main_pane)
        main_pane.add(left_panel, minsize=320)
        main_pane.add(right_panel, minsize=560)

        sql_frame = tk.LabelFrame(left_panel, text="SQL Query", padx=5, pady=5)
        sql_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 8))
        self.sql_text = tk.Text(sql_frame, height=11, font=("Courier", 11))
        self.sql_text.pack(fill=tk.BOTH, expand=True)

        schema_frame = tk.LabelFrame(left_panel, text="Schema (double-click table to query)", padx=5, pady=5)
        schema_frame.pack(fill=tk.BOTH, expand=True)

        self.schema_tree = ttk.Treeview(schema_frame)
        self.schema_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.schema_tree.bind("<Double-1>", self.on_schema_double_click)

        schema_scroll = tk.Scrollbar(schema_frame, command=self.schema_tree.yview)
        schema_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.schema_tree.configure(yscrollcommand=schema_scroll.set)
        self.schema_tree["columns"] = ("type",)
        self.schema_tree.heading("#0", text="Table / Column")
        self.schema_tree.heading("type", text="Type")
        self.schema_tree.column("#0", width=220, anchor=tk.W)
        self.schema_tree.column("type", width=100, anchor=tk.W)

        results_frame = tk.LabelFrame(right_panel, text="Results", padx=5, pady=5)
        results_frame.pack(fill=tk.BOTH, expand=True)

        tree_scroll_y = tk.Scrollbar(results_frame)
        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        tree_scroll_x = tk.Scrollbar(results_frame, orient="horizontal")
        tree_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)

        self.tree = ttk.Treeview(results_frame, yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)
        self.tree.pack(fill=tk.BOTH, expand=True)
        tree_scroll_y.config(command=self.tree.yview)
        tree_scroll_x.config(command=self.tree.xview)

        status_bar = tk.Label(self, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))

    def browse_db(self):
        file_path = filedialog.askopenfilename(
            title="Select SQLite database",
            filetypes=[("SQLite DB", "*.db *.sqlite *.sqlite3"), ("All files", "*.*")],
        )
        if file_path:
            self.db_path.set(file_path)
            self.refresh_schema()

    def get_connection(self):
        db = self.db_path.get().strip()
        if not db:
            raise FileNotFoundError("No database path provided.")
        path = Path(db)
        if not path.exists():
            raise FileNotFoundError(f"Database file not found: {path}")
        return sqlite3.connect(path)

    def build_preset_sql(self):
        selection = self.query_var.get()
        template = PRESET_TEMPLATES.get(selection, "")
        if not template:
            return ""

        rank_limit = self.rank_limit_var.get().strip() or "10"
        try:
            rank_limit_int = int(rank_limit)
        except ValueError:
            rank_limit_int = 10

        return template.format(rank_limit=rank_limit_int)

    def on_query_select(self, event=None):
        sql = self.build_preset_sql()
        if sql:
            self.sql_text.delete("1.0", tk.END)
            self.sql_text.insert("1.0", sql)

    def refresh_schema(self):
        self.schema_tree.delete(*self.schema_tree.get_children())
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            tables = cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()

            table_count = 0
            for (table_name,) in tables:
                table_id = self.schema_tree.insert("", tk.END, text=table_name, values=("table",), open=True)
                columns = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
                for col in columns:
                    col_name = col[1]
                    col_type = col[2] or ""
                    self.schema_tree.insert(table_id, tk.END, text=col_name, values=(col_type,))
                table_count += 1

            conn.close()
            self.status_var.set(f"Connected to {Path(self.db_path.get()).name}. Loaded {table_count} table(s).")
        except Exception as e:
            self.status_var.set("Schema refresh failed.")
            messagebox.showerror("Schema Error", str(e))

    def on_schema_double_click(self, event=None):
        item_id = self.schema_tree.focus()
        if not item_id:
            return

        parent_id = self.schema_tree.parent(item_id)
        if parent_id:
            return

        table_name = self.schema_tree.item(item_id, "text")
        if table_name:
            sql = f"SELECT * FROM {table_name} LIMIT 100;"
            self.sql_text.delete("1.0", tk.END)
            self.sql_text.insert("1.0", sql)
            self.status_var.set(f"Loaded quick query for table: {table_name}")

    def run_query(self):
        query = self.sql_text.get("1.0", tk.END).strip()
        if not query:
            messagebox.showwarning("Warning", "Query is empty!")
            return

        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(query)

            if cursor.description is None:
                conn.commit()
                conn.close()
                self.last_columns = []
                self.last_rows = []
                self.update_treeview([], [])
                self.status_var.set("Statement executed successfully.")
                return

            columns = [description[0] for description in cursor.description]
            rows = cursor.fetchall()
            conn.close()

            self.last_columns = columns
            self.last_rows = rows
            self.update_treeview(columns, rows)
            self.status_var.set(f"Query executed successfully. Returned {len(rows)} row(s).")
        except sqlite3.Error as e:
            messagebox.showerror("Database Error", f"An error occurred:{e}")
            self.status_var.set("Error executing query.")
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred:{e}")
            self.status_var.set("Unexpected error.")

    def export_csv(self):
        if not self.last_columns:
            messagebox.showinfo("Export CSV", "Run a SELECT query first so there is data to export.")
            return

        file_path = filedialog.asksaveasfilename(
            title="Save results as CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(self.last_columns)
                writer.writerows(self.last_rows)
            self.status_var.set(f"Exported {len(self.last_rows)} row(s) to {Path(file_path).name}.")
        except Exception as e:
            messagebox.showerror("Export Error", f"Could not export CSV:{e}")
            self.status_var.set("CSV export failed.")

    def update_treeview(self, columns, rows):
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = columns
        self.tree["show"] = "headings" if columns else "tree"

        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=130, minwidth=60, stretch=tk.YES)

        for row in rows:
            self.tree.insert("", tk.END, values=row)


if __name__ == "__main__":
    app = PokemonDBViewer()
    app.mainloop()
