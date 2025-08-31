import os
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
from datetime import datetime
from transformers import MarianMTModel, MarianTokenizer
import torch

# Ensure sentencepiece is installed
try:
    import sentencepiece
except ImportError:
    os.system("pip install sentencepiece")
    import sentencepiece

# Ensure python-docx is installed
try:
    from docx import Document
except ImportError:
    os.system("pip install python-docx")
    from docx import Document


class ChineseToEnglishGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🇨🇳 Mandarin Chinese → English Translator")
        self.root.geometry("950x650")
        self.root.configure(bg="#1a1a2e")

        # Local model path (existing Chinese → English model)
        self.model_path = r"C:\Users\intel\models\opus-mt-zh-en"
        self.model = None
        self.tokenizer = None
        self.is_translating = False

        self.build_gui()
        self.load_model_async()

    def build_gui(self):
        # Header
        self.header = tk.Label(self.root, text="🇨🇳 Mandarin Chinese → English Translator",
                               font=("Helvetica", 24, "bold"), bg="#162447", fg="#e43f5a", pady=15)
        self.header.pack(fill=tk.X)

        # Input Frame
        self.input_frame = tk.Frame(self.root, bg="#1f4068")
        self.input_frame.pack(fill=tk.X, padx=30, pady=(20, 10))
        self.input_label = tk.Label(self.input_frame, text="Enter Chinese Text or Paste Content:",
                                    bg="#1f4068", fg="#e0e0e0", font=("Helvetica", 12, "bold"))
        self.input_label.pack(anchor="w", padx=10, pady=(5, 0))
        self.input_text = tk.Text(self.input_frame, height=10, font=("Helvetica", 12),
                                  wrap=tk.WORD, bg="#e0e0e0", fg="#1f4068", relief="flat", padx=10, pady=10)
        self.input_text.pack(fill=tk.X, padx=10, pady=10)

        # Buttons
        self.button_frame = tk.Frame(self.root, bg="#1a1a2e")
        self.button_frame.pack(fill=tk.X, padx=30, pady=(0, 20))
        self.translate_btn = tk.Button(self.button_frame, text="Translate", bg="#e43f5a", fg="white",
                                       font=("Helvetica", 12, "bold"), relief="flat", padx=25, pady=10,
                                       command=self.translate_async, state=tk.DISABLED)
        self.translate_btn.pack(side="left", padx=10)

        self.clear_btn = tk.Button(self.button_frame, text="Clear Input", bg="#0f3460", fg="white",
                                   font=("Helvetica", 12, "bold"), relief="flat", padx=25, pady=10,
                                   command=self.clear_input)
        self.clear_btn.pack(side="left", padx=10)

        self.load_file_btn = tk.Button(self.button_frame, text="Load Word File", bg="#0f3460", fg="white",
                                       font=("Helvetica", 12, "bold"), relief="flat", padx=25, pady=10,
                                       command=self.load_docx)
        self.load_file_btn.pack(side="left", padx=10)

        self.save_btn = tk.Button(self.button_frame, text="Save Translation", bg="#0f3460", fg="white",
                                  font=("Helvetica", 12, "bold"), relief="flat", padx=25, pady=10,
                                  command=self.save_translation)
        self.save_btn.pack(side="right", padx=10)

        # Output Frame
        self.output_frame = tk.Frame(self.root, bg="#1f4068")
        self.output_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=(0, 20))
        self.output_label = tk.Label(self.output_frame, text="English Translation:",
                                     bg="#1f4068", fg="#e0e0e0", font=("Helvetica", 12, "bold"))
        self.output_label.pack(anchor="w", padx=10, pady=(5, 0))
        self.output_text = tk.Text(self.output_frame, height=12, font=("Helvetica", 12),
                                   wrap=tk.WORD, bg="#e0e0e0", fg="#1f4068", relief="flat", padx=10, pady=10)
        self.output_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.output_text.insert("1.0", "Translation will appear here...")
        self.output_text.config(state="disabled")

        # Status
        self.status_label = tk.Label(self.root, text="Loading translation model...", bg="#1a1a2e",
                                     fg="#00adb5", font=("Helvetica", 10))
        self.status_label.pack(side="bottom", fill=tk.X, pady=5)

    def load_docx(self):
        filename = filedialog.askopenfilename(filetypes=[("Word Files", "*.docx")])
        if filename:
            doc = Document(filename)
            text = ""
            for para in doc.paragraphs:
                text += para.text + "\n\n"
            self.input_text.delete("1.0", "end")
            self.input_text.insert("1.0", text.strip())

    def load_model_async(self):
        def load_model():
            try:
                self.update_status("Loading translation model...")
                if os.path.exists(self.model_path):
                    try:
                        self.tokenizer = MarianTokenizer.from_pretrained(self.model_path)
                        self.model = MarianMTModel.from_pretrained(self.model_path)
                        self.model.to("cpu")
                        self.root.after(0, self.model_loaded)
                        return
                    except:
                        self.update_status("Local model incomplete, redownloading...")

                # fallback: download if missing
                model_name = "Helsinki-NLP/opus-mt-zh-en"
                self.tokenizer = MarianTokenizer.from_pretrained(model_name, cache_dir=self.model_path)
                self.model = MarianMTModel.from_pretrained(model_name, cache_dir=self.model_path)
                self.model.to("cpu")
                self.root.after(0, self.model_loaded)
            except Exception as e:
                self.root.after(0, lambda e=e: self.model_error(str(e)))

        threading.Thread(target=load_model, daemon=True).start()

    def model_loaded(self):
        self.update_status("Model loaded successfully! Ready to translate.")
        self.translate_btn.config(state="normal")

    def model_error(self, error):
        self.update_status(f"Model load error: {error}")
        messagebox.showerror("Model Error", f"Failed to load model:\n{error}")

    def translate_async(self):
        if self.is_translating or self.model is None: return
        text = self.input_text.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Empty Input", "Please enter text to translate.")
            return

        def translate():
            try:
                self.is_translating = True
                self.update_status("Translating...")
                paragraphs = text.split("\n\n")
                translated_paragraphs = []

                for para in paragraphs:
                    if para.strip():
                        tokens = self.tokenizer(para, return_tensors="pt", truncation=False)["input_ids"]
                        out = self.model.generate(tokens)
                        translated_text = self.tokenizer.decode(out[0], skip_special_tokens=True)
                        translated_paragraphs.append(translated_text)
                    else:
                        translated_paragraphs.append("")

                result = "\n\n".join(translated_paragraphs)
                self.root.after(0, lambda: self.show_translation(result))
            except Exception as e:
                self.root.after(0, lambda: self.translation_error(str(e)))

        threading.Thread(target=translate, daemon=True).start()

    def show_translation(self, text):
        self.is_translating = False
        self.output_text.config(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", text)
        self.output_text.config(state="disabled")
        self.update_status("Translation complete!")

    def translation_error(self, error):
        self.is_translating = False
        self.update_status(f"Translation failed: {error}")
        messagebox.showerror("Translation Error", error)

    def clear_input(self):
        self.input_text.delete("1.0", "end")

    def save_translation(self):
        text = self.output_text.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Nothing to Save", "No translation available to save.")
            return
        filename = filedialog.asksaveasfilename(defaultextension=".txt",
                                                filetypes=[("Text files","*.txt"),("All files","*.*")],
                                                title="Save Translation",
                                                initialfile=f"translation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        if filename:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(text)
            messagebox.showinfo("Saved", f"Translation saved to {os.path.basename(filename)}")

    def update_status(self, message):
        self.status_label.config(text=message)


if __name__ == "__main__":
    root = tk.Tk()
    app = ChineseToEnglishGUI(root)
    root.mainloop()
