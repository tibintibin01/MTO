# -*- coding: utf-8 -*-
import customtkinter as ctk
from PIL import Image
import threading
import requests
import os
from typing import Callable, List, Dict

class CommandPalette(ctk.CTkToplevel):
    def __init__(self, master, user_data, on_select: Callable):
        super().__init__(master)
        
        self.user_data = user_data
        self.on_select = on_select # Callback for navigation/actions
        
        # Setup Toplevel
        self.title("Command Palette")
        self.geometry("650x450")
        self.overrideredirect(True) # Remove border/titlebar
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.95)
        
        # Center on screen
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width // 2) - (650 // 2)
        y = (screen_height // 2) - (450 // 2)
        self.geometry(f"+{x}+{y}")
        
        self.setup_ui()
        self.bind_keys()
        
        # Focus management
        self.after(10, self.search_entry.focus_set)
        self.bind("<FocusOut>", lambda e: self.destroy())

    def setup_ui(self):
        self.configure(fg_color="#1a1a1a")
        
        # Main Border Frame
        self.main_frame = ctk.CTkFrame(self, corner_radius=15, border_width=1, border_color="#333")
        self.main_frame.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Search Header
        self.search_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.search_frame.pack(fill="x", padx=20, pady=(20, 10))
        
        self.search_entry = ctk.CTkEntry(
            self.search_frame, 
            placeholder_text="Search properties, receipts, or type '>' for actions...",
            font=("Segoe UI", 16),
            height=50,
            fg_color="#262626",
            border_width=0,
            corner_radius=10
        )
        self.search_entry.pack(fill="x")
        self.search_entry.bind("<KeyRelease>", self.on_key_release)
        
        # Results Area
        self.results_scroll = ctk.CTkScrollableFrame(self.main_frame, fg_color="transparent")
        self.results_scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.result_items: List[ctk.CTkFrame] = []
        self.selected_index = -1
        
        # Initial: Show Quick Actions
        self.perform_search("")

    def bind_keys(self):
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Up>", self.move_selection_up)
        self.bind("<Down>", self.move_selection_down)
        self.bind("<Return>", self.execute_selected)

    def on_key_release(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return
        
        query = self.search_entry.get().strip()
        self.perform_search(query)

    def perform_search(self, query):
        # In a real app, this would hit the API
        # Since we're in the same process for this demo, we'll simulate the API call
        # but structured for easy migration to requests.get later
        def fetch():
            try:
                # Use the API Client instead of direct backend import
                import api_clients.search_service as search_svc
                
                if not query:
                    results = search_svc.get_quick_actions()
                else:
                    results = search_svc.global_search(query)
                
                self.after(0, lambda: self.render_results(results))
            except Exception as e:
                print(f"Search error: {e}")

        threading.Thread(target=fetch, daemon=True).start()

    def render_results(self, results):
        # Clear old
        for widget in self.results_scroll.winfo_children():
            widget.destroy()
        self.result_items = []
        self.selected_index = -1
        
        if not results:
            ctk.CTkLabel(self.results_scroll, text="No results found.", font=("Segoe UI", 12), text_color="gray").pack(pady=20)
            return

        for i, res in enumerate(results):
            item = ctk.CTkFrame(self.results_scroll, fg_color="transparent", corner_radius=8, cursor="hand2")
            item.pack(fill="x", pady=2, padx=5)
            
            # Content
            title_lbl = ctk.CTkLabel(item, text=res["title"], font=("Segoe UI", 13, "bold"), anchor="w")
            title_lbl.pack(fill="x", padx=15, pady=(8, 2))
            
            if "subtitle" in res:
                sub_lbl = ctk.CTkLabel(item, text=res["subtitle"], font=("Segoe UI", 11), text_color="gray", anchor="w")
                sub_lbl.pack(fill="x", padx=15, pady=(0, 8))
            
            # Hover effect & selection
            item.bind("<Enter>", lambda e, idx=i: self.highlight_item(idx))
            item.bind("<Button-1>", lambda e, r=res: self.select_result(r))
            
            # Store metadata in widget for execution
            item._mto_data = res
            self.result_items.append(item)

    def highlight_item(self, index):
        # Reset others
        for item in self.result_items:
            item.configure(fg_color="transparent")
        
        if 0 <= index < len(self.result_items):
            self.result_items[index].configure(fg_color="#333")
            self.selected_index = index

    def move_selection_down(self, e):
        new_idx = self.selected_index + 1
        if new_idx < len(self.result_items):
            self.highlight_item(new_idx)

    def move_selection_up(self, e):
        new_idx = self.selected_index - 1
        if new_idx >= 0:
            self.highlight_item(new_idx)

    def execute_selected(self, e=None):
        if 0 <= self.selected_index < len(self.result_items):
            data = self.result_items[self.selected_index]._mto_data
            self.select_result(data)

    def select_result(self, result):
        self.on_select(result)
        self.destroy()
