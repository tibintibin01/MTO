import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from theme_manager import ModernTheme
import api_clients.auth_service as auth
import api_clients.system_service as system
import threading

class UserAccessPage:
    def __init__(self, parent, user):
        self.parent = parent
        self.user = user
        self.selected_user = None
        self.can_manage_users = auth.has_permission(user, "manage_users")
        self.setup_ui()
        self.refresh_users()

    def setup_ui(self):
        self.container = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        # Main Layout: Two columns
        self.container.grid_columnconfigure(0, weight=3) # User Directory
        self.container.grid_columnconfigure(1, weight=1) # Admin Action Panel
        self.container.grid_rowconfigure(0, weight=1)

        # --- LEFT COLUMN: USER DIRECTORY ---
        directory_fr = ctk.CTkFrame(self.container)
        directory_fr.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        
        ctk.CTkLabel(directory_fr, text="USER DIRECTORY", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=20, pady=(15, 10))
        
        # Action Bar in directory
        dir_actions = ctk.CTkFrame(directory_fr, fg_color="transparent")
        dir_actions.pack(fill="x", padx=20, pady=(0, 10))
        
        if self.can_manage_users:
            ctk.CTkButton(dir_actions, text="+ REGISTER NEW USER", command=self.open_register_modal,
                          fg_color="#3498db", hover_color="#2980b9", height=32, font=("Segoe UI", 10, "bold")).pack(side="left")

        ctk.CTkButton(dir_actions, text="🔄 REFRESH", command=self.refresh_users,
                      fg_color="transparent", border_width=1, border_color="#34495e", 
                      text_color="#34495e", width=100, height=32).pack(side="right")
        
        # Table Styling
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("User.Treeview", rowheight=40, font=("Segoe UI", 10), background="#2b2b2b", fieldbackground="#2b2b2b", foreground="white")
        style.configure("User.Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#333333", foreground="white")

        self.tree = ttk.Treeview(directory_fr, columns=("ID", "Status", "Full Name", "Username", "Role", "Last Login"), show="headings", style="User.Treeview")
        self.tree.heading("ID", text="ID")
        self.tree.heading("Status", text="STATUS")
        self.tree.heading("Full Name", text="FULL NAME")
        self.tree.heading("Username", text="USERNAME")
        self.tree.heading("Role", text="ROLE")
        self.tree.heading("Last Login", text="LAST LOGIN")
        
        self.tree.column("ID", width=0, stretch=tk.NO)
        self.tree.column("Status", width=100, anchor="center")
        self.tree.column("Full Name", width=250)
        self.tree.column("Username", width=150)
        self.tree.column("Role", width=120, anchor="center")
        
        scrolly = ttk.Scrollbar(directory_fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrolly.set)

        # Zebra Tags
        self.tree.tag_configure('oddrow', background="#2b2b2b", foreground="white")
        self.tree.tag_configure('evenrow', background="#333333", foreground="white")

        self.tree.pack(side="left", fill="both", expand=True, padx=(20, 0), pady=(0, 20))
        scrolly.pack(side="right", fill="y", padx=(0, 20), pady=(0, 20))
        
        self.tree.bind("<<TreeviewSelect>>", self.on_user_selected)

        # --- RIGHT COLUMN: ADMIN ACTION PANEL ---
        self.admin_panel = ctk.CTkFrame(self.container, fg_color="#f1f2f6" if not self.can_manage_users else "transparent")
        self.admin_panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        
        if not self.can_manage_users:
            ctk.CTkLabel(self.admin_panel, text="ADMIN ONLY AREA", font=("Segoe UI", 11, "bold"), text_color="gray").pack(pady=50)
            return

        ctk.CTkLabel(self.admin_panel, text="ADMIN COMMAND CENTER", font=("Segoe UI", 12, "bold"), text_color="#2980b9").pack(pady=(15, 20))

        # Selected User Info Card
        self.user_card = ctk.CTkFrame(self.admin_panel)
        self.user_card.pack(fill="x", padx=15, pady=(0, 20))
        
        self.name_lbl = ctk.CTkLabel(self.user_card, text="Select a user...", font=("Segoe UI", 12, "bold"))
        self.name_lbl.pack(pady=(15, 5))
        self.role_lbl = ctk.CTkLabel(self.user_card, text="", font=("Segoe UI", 10), text_color="gray")
        self.role_lbl.pack(pady=(0, 15))

        # Action Panel Inner
        self.action_fr = ctk.CTkFrame(self.admin_panel, fg_color="transparent")
        self.action_fr.pack(fill="both", expand=True, padx=15)
        
        # Role Change
        ctk.CTkLabel(self.action_fr, text="SYSTEM ROLE", font=("Segoe UI", 9, "bold"), text_color="gray").pack(anchor="w")
        self.role_cb = ctk.CTkComboBox(self.action_fr, values=["admin", "cashier", "encoder", "viewer"], height=35)
        self.role_cb.pack(fill="x", pady=(5, 15))
        
        # Account Status
        ctk.CTkLabel(self.action_fr, text="ACCOUNT STATUS", font=("Segoe UI", 9, "bold"), text_color="gray").pack(anchor="w")
        self.status_var = tk.BooleanVar(value=True)
        self.status_sw = ctk.CTkSwitch(self.action_fr, text="Account Enabled", variable=self.status_var, command=self.toggle_account_status)
        self.status_sw.pack(anchor="w", pady=(5, 25))

        # High-Security Actions
        ctk.CTkLabel(self.action_fr, text="SECURITY ACTIONS", font=("Segoe UI", 9, "bold"), text_color="gray").pack(anchor="w")
        
        ctk.CTkButton(self.action_fr, text="FORCE PASSWORD RESET", command=self.reset_password, 
                      fg_color="#e67e22", hover_color="#d35400", height=40).pack(fill="x", pady=(10, 10))
        
        self.save_changes_btn = ctk.CTkButton(self.action_fr, text="APPLY ROLE CHANGE", command=self.apply_role_change,
                                               fg_color="#2ecc71", hover_color="#27ae60", height=40)
        self.save_changes_btn.pack(fill="x", pady=(10, 30))

        # Mini Activity Trace (Audit Logs for this user)
        ctk.CTkLabel(self.action_fr, text="LATEST ACTIVITY TRACE", font=("Segoe UI", 9, "bold"), text_color="gray").pack(anchor="w")
        self.audit_tree = ttk.Treeview(self.action_fr, columns=("Action"), show="", height=5)
        self.audit_tree.column("#0", width=0, stretch=tk.NO)
        self.audit_tree.column("Action", width=200)
        self.audit_tree.pack(fill="x", pady=5)
        
        # Disable Admin UI by default
        self.set_admin_ui_state("disabled")

    def set_admin_ui_state(self, state):
        self.role_cb.configure(state=state)
        self.status_sw.configure(state=state)
        self.save_changes_btn.configure(state=state)
        # Note: Password reset is special, handled in its own func

    def refresh_users(self):
        def worker():
            try:
                users = auth.get_all_users()
                self.container.after(0, lambda: self._update_user_table(users))
            except Exception as e:
                self.container.after(
                    0, lambda err=e: messagebox.showerror("Refresh Error", str(err))
                )
        threading.Thread(target=worker, daemon=True).start()

    def _update_user_table(self, users):
        for row in self.tree.get_children(): self.tree.delete(row)
        for i, u in enumerate(users):
            status_text = "🟢 ACTIVE" if u["is_active"] else "🔴 DISABLED"
            ts_raw = u.get("last_login")
            if isinstance(ts_raw, str):
                login_time = ts_raw.replace("T", " ")[:16]
            elif ts_raw:
                login_time = ts_raw.strftime("%Y-%m-%d %H:%M")
            else:
                login_time = "Never"
            
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            self.tree.insert("", "end", values=(u["id"], status_text, u["full_name"], u["username"], u["role"].upper(), login_time), tags=(tag,))

    def on_user_selected(self, event=None):
        if not self.can_manage_users: return
        
        sel = self.tree.selection()
        if not sel: return
        
        vals = self.tree.item(sel[0])["values"]
        self.selected_user = {
            "id": vals[0],
            "status": vals[1],
            "full_name": vals[2],
            "username": vals[3],
            "role": vals[4].lower()
        }
        
        # Update Admin Panel
        self.name_lbl.configure(text=self.selected_user["full_name"])
        self.role_lbl.configure(text=f"Username: {self.selected_user['username']}")
        self.role_cb.set(self.selected_user["role"])
        self.status_var.set("ACTIVE" in self.selected_user["status"])
        
        self.set_admin_ui_state("normal")
        
        # Prevent self-disabling
        current_id = self.user.get("id") if isinstance(self.user, dict) else None
        if current_id and int(self.selected_user["id"]) == int(current_id):
            self.status_sw.configure(state="disabled")
            self.role_cb.configure(state="disabled")
            self.save_changes_btn.configure(state="disabled")
        
        # Load Audit History for this user
        self.refresh_audit_trace(self.selected_user["id"])

    def toggle_account_status(self):
        if not self.selected_user: return
        new_status = self.status_var.get()
        msg = "Enable this account?" if new_status else "Disable this account? User will be blocked from logging in."
        if not messagebox.askyesno("Confirm Status Change", msg):
            self.status_var.set(not new_status)
            return
        
        try:
            auth.update_user(self.selected_user["id"], is_active=new_status)
            self.refresh_users()
            self.refresh_audit_trace(self.selected_user["id"])
        except Exception as e:
            messagebox.showerror("Update Error", str(e))

    def apply_role_change(self):
        if not self.selected_user: return
        new_role = self.role_cb.get()
        if not messagebox.askyesno("Confirm Role Change", f"Change {self.selected_user['username']}'s role to {new_role.upper()}?"):
            return
        
        try:
            auth.update_user(self.selected_user["id"], role=new_role)
            self.refresh_users()
            self.refresh_audit_trace(self.selected_user["id"])
            messagebox.showinfo("Success", "Role updated successfully.")
        except Exception as e:
            messagebox.showerror("Update Error", str(e))

    def reset_password(self):
        if not self.selected_user: return
        new_pass = simpledialog.askstring("Reset Password", f"Enter new password for {self.selected_user['username']}:", show="*")
        if not new_pass: return
        
        if len(new_pass) < 6:
            messagebox.showerror("Error", "Password must be at least 6 characters.")
            return
            
        try:
            auth.reset_user_password(self.selected_user["id"], new_pass)
            messagebox.showinfo("Success", "Password reset successfully.")
            self.refresh_audit_trace(self.selected_user["id"])
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def refresh_audit_trace(self, user_id):
        def worker():
            try:
                logs = auth.get_audit_logs(user_id=user_id)
                self.container.after(0, lambda: self._update_audit_trace(logs))
            except: pass # Silent fail for mini-trace
        threading.Thread(target=worker, daemon=True).start()

    def _update_audit_trace(self, logs):
        for row in self.audit_tree.get_children(): self.audit_tree.delete(row)
        for log in logs[:10]: # Only show last 10
            ts = log["timestamp"]
            # Formatting timestamp or using a short action description
            desc = f"{log['action']}"
            self.audit_tree.insert("", "end", values=(desc,))

    def open_register_modal(self):
        RegisterUserModal(self.container, self.refresh_users)

class RegisterUserModal(ctk.CTkToplevel):
    def __init__(self, parent, callback):
        super().__init__(parent)
        self.title("New User Registration")
        self.geometry("450x600")
        self.resizable(False, False)
        self.callback = callback
        
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.attributes("-topmost", True)
        
        # Center
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-450)//2}+{(sh-600)//2}")
        
        self.setup_ui()

    def setup_ui(self):
        self.configure(fg_color="white")
        
        # Header
        header_fr = ctk.CTkFrame(self, fg_color="#3498db", height=100, corner_radius=0)
        header_fr.pack(fill="x")
        ctk.CTkLabel(header_fr, text="👤 REGISTER NEW PERSONNEL", font=("Segoe UI", 16, "bold"), text_color="white").pack(pady=35)

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=40, pady=30)

        # Full Name
        ctk.CTkLabel(form, text="FULL NAME", font=("Segoe UI", 9, "bold"), text_color="gray").pack(anchor="w")
        self.name_ent = ctk.CTkEntry(form, placeholder_text="e.g. Juan Dela Cruz", height=40)
        self.name_ent.pack(fill="x", pady=(5, 15))

        # Username
        ctk.CTkLabel(form, text="USERNAME", font=("Segoe UI", 9, "bold"), text_color="gray").pack(anchor="w")
        self.user_ent = ctk.CTkEntry(form, placeholder_text="e.g. juandc", height=40)
        self.user_ent.pack(fill="x", pady=(5, 15))

        # Role
        ctk.CTkLabel(form, text="SYSTEM ROLE", font=("Segoe UI", 9, "bold"), text_color="gray").pack(anchor="w")
        self.role_cb = ctk.CTkComboBox(form, values=["cashier", "encoder", "viewer", "admin"], height=40)
        self.role_cb.set("cashier")
        self.role_cb.pack(fill="x", pady=(5, 15))

        # Initial Password
        ctk.CTkLabel(form, text="INITIAL PASSWORD", font=("Segoe UI", 9, "bold"), text_color="gray").pack(anchor="w")
        self.pass_ent = ctk.CTkEntry(form, placeholder_text="At least 6 characters", height=40, show="*")
        self.pass_ent.pack(fill="x", pady=(5, 30))

        # Buttons
        btn_fr = ctk.CTkFrame(self, fg_color="transparent")
        btn_fr.pack(fill="x", side="bottom", pady=30, padx=40)

        ctk.CTkButton(btn_fr, text="CANCEL", command=self.destroy, fg_color="#95a5a6", height=40, width=100).pack(side="left")
        ctk.CTkButton(btn_fr, text="CREATE ACCOUNT", command=self.save, fg_color="#2ecc71", height=40, width=250).pack(side="right")

    def save(self):
        name = self.name_ent.get().strip()
        user = self.user_ent.get().strip().lower()
        role = self.role_cb.get()
        pwd = self.pass_ent.get().strip()

        if not name or not user or not pwd:
            messagebox.showerror("Error", "All fields are required!")
            return
        
        if len(pwd) < 6:
            messagebox.showerror("Error", "Password must be at least 6 characters.")
            return

        try:
            res = auth.create_user(name, user, pwd, role)
            if res.get("status") == "created":
                messagebox.showinfo("Success", f"User {user} registered successfully.")
                self.callback()
                self.destroy()
            else:
                messagebox.showerror("Error", "Failed to create account.")
        except Exception as e:
            messagebox.showerror("Error", str(e))
