import os
import tkinter as tk
from tkinter import messagebox
import subprocess
import threading
import time
import customtkinter as ctk

# Set the appearance mode and default color theme for a sleek look
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Base path where all language folders are located
BASE_PATH = r"C:\Users\intel\Desktop\translation tools\New folder"

# Mapping target languages to their script paths
TARGET_LANGUAGES = {
    "English": os.path.join(BASE_PATH, "english", "english_to_english.py"),
    "Bengali": os.path.join(BASE_PATH, "bengali", "english_to_bengali.py"),
    "French": os.path.join(BASE_PATH, "french", "english_to_french.py"),
    "Hindi": os.path.join(BASE_PATH, "hindi", "english_to_hindi.py"),
    "Indonesian": os.path.join(BASE_PATH, "Indonesian(Malay)", "english_to_Indonesian(Malay).py"),
    "Japanese": os.path.join(BASE_PATH, "japanese", "english_to_japanese.py"),
    "Mandarin Chinese": os.path.join(BASE_PATH, "Mandarin_Chinese", "english_to_Mandarin_Chinese.py"),
    "Arabic": os.path.join(BASE_PATH, "modern standard arabic", "english_to_modern_Standard_Arabic.py"),
    "Portuguese": os.path.join(BASE_PATH, "portugese", "english_to_portugese.py"),
    "Russian": os.path.join(BASE_PATH, "russian", "english_to_russian.py"),
    "Spanish": os.path.join(BASE_PATH, "spanish", "english_to_spanish.py"),
}

class RealtimeControlPanel(ctk.CTk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.title("🚀 Translator Pro Control Panel")
        self.geometry("720x520")
        self.resizable(False, False)

        try:
            self.font = ctk.CTkFont(family="Orbitron", size=20, weight="bold")
        except:
            self.font = ctk.CTkFont(family="Helvetica", size=20, weight="bold")

        self.build_gui()

    def build_gui(self):
        main_frame = ctk.CTkFrame(self, corner_radius=15, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=30, pady=30)
        
        header = ctk.CTkLabel(main_frame, text="🛰 Translation Command Center", font=self.font, text_color="#00ffff")
        header.pack(pady=(20, 60))

        selection_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        selection_frame.pack(pady=20)

        source_label = ctk.CTkLabel(selection_frame, text="Source Language:", font=ctk.CTkFont(size=14))
        source_label.grid(row=0, column=0, padx=(10, 50), pady=10)
        
        self.source_var = ctk.StringVar(value="English")
        source_entry = ctk.CTkEntry(selection_frame, textvariable=self.source_var, font=ctk.CTkFont(size=14), width=200, state="disabled")
        source_entry.grid(row=0, column=1, padx=10, pady=10)

        target_label = ctk.CTkLabel(selection_frame, text="Target Language:", font=ctk.CTkFont(size=14))
        target_label.grid(row=1, column=0, padx=(10, 50), pady=10)
        
        self.target_var = ctk.StringVar()
        target_dropdown = ctk.CTkComboBox(selection_frame, variable=self.target_var, values=list(TARGET_LANGUAGES.keys()), font=ctk.CTkFont(size=14), width=200)
        target_dropdown.grid(row=1, column=1, padx=10, pady=10)
        target_dropdown.set("English")

        self.launch_btn = ctk.CTkButton(main_frame, text="Launch Translator", 
                                        font=ctk.CTkFont(size=16, weight="bold"),
                                        command=self.validate_and_launch,
                                        width=250, height=50, corner_radius=10,
                                        hover_color="#0066cc", fg_color="#007bff")
        self.launch_btn.pack(pady=40)
        
        self.status_label = ctk.CTkLabel(main_frame, text="", font=ctk.CTkFont(size=12, slant="italic"), wraplength=450)
        self.status_label.pack(pady=(10, 20))

        footer = ctk.CTkLabel(self, text="Control Panel v4.0 | Developed by You", font=ctk.CTkFont(size=10))
        footer.pack(side="bottom", pady=10)

    def validate_and_launch(self):
        target_language = self.target_var.get()
        script_path = TARGET_LANGUAGES.get(target_language)

        if not script_path or not os.path.exists(script_path):
            messagebox.showerror("Error", f"🚫 Script file not found for {target_language}.\n\nExpected path:\n{script_path}")
            self.status_label.configure(text="Validation Failed!")
            return

        self.launch_btn.configure(state="disabled", text="Launching...")
        self.status_label.configure(text="Validating script path...")
        threading.Thread(target=self.animate_and_launch, args=(script_path,), daemon=True).start()

    def animate_and_launch(self, script_path):
        try:
            # We use subprocess.Popen to get a reference to the process and its output stream.
            process = subprocess.Popen(["python", script_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.status_label.configure(text="Translator script is running...")

            # Real-time update loop
            for line in process.stdout:
                # Update the status label with each line of output
                self.status_label.configure(text=line.strip())
                self.update_idletasks() # Force GUI update

            # Wait for the process to fully complete
            process.wait()

            # Final status update
            if process.returncode == 0:
                self.status_label.configure(text="✅ Launch done!")
            else:
                self.status_label.configure(text=f"❌ Script failed with code: {process.returncode}")

        except Exception as e:
            self.status_label.configure(text=f"❌ Failed to launch: {e}")
            messagebox.showerror("Launch Error", f"Failed to launch translator: {e}")
        
        # Reset the GUI after a short delay
        time.sleep(1.5)
        self.status_label.configure(text="")
        self.launch_btn.configure(state="normal", text="Launch Translator")

if __name__ == "__main__":
    app = RealtimeControlPanel()
    app.mainloop()