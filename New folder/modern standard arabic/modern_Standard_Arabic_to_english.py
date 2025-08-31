# Arabic -> English offline translator (Tkinter GUI)
# - Model: Helsinki-NLP/opus-mt-ar-en
# - Local cache folder used: C:\Users\intel\models\opus-mt-ar-en
# First run must be online to download the model; subsequent runs use the local copy.

import os
import threading
import traceback
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox
from transformers import MarianMTModel, MarianTokenizer
import torch

# optional: python-docx used for loading .docx files
try:
    from docx import Document
except Exception:
    Document = None

# Ensure sentencepiece present (required by many Marian tokenizers)
try:
    import sentencepiece  # noqa: F401
except Exception:
    # Try to install -- if user has no internet this will fail; we handle later
    try:
        os.system("pip install sentencepiece")
        import sentencepiece  # noqa: F401
    except Exception:
        pass


class ArabicToEnglishGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🇸🇦 Arabic → English Translator (Offline-ready)")
        self.root.geometry("980x680")
        self.root.configure(bg="#111218")

        # Model config
        self.model_cache_dir = r"C:\Users\intel\models"              # top-level cache dir
        self.model_folder = os.path.join(self.model_cache_dir, "opus-mt-ar-en")  # exact local folder to save model
        self.model_name = "Helsinki-NLP/opus-mt-ar-en"               # hub id (used for first-time download)
        os.makedirs(self.model_cache_dir, exist_ok=True)
        os.makedirs(self.model_folder, exist_ok=True)

        self.tokenizer = None
        self.model = None
        self.is_translating = False

        self.build_gui()
        self.load_model_async()

    def build_gui(self):
        # Header
        header = tk.Label(self.root, text="🇸🇦 Arabic → English Translator",
                          font=("Segoe UI", 22, "bold"), bg="#0b1220", fg="#ffd6a5", pady=12)
        header.pack(fill=tk.X, padx=8, pady=(8, 10))

        # Input area
        in_frame = tk.Frame(self.root, bg="#071024")
        in_frame.pack(fill=tk.X, padx=12, pady=(4, 8))
        in_label = tk.Label(in_frame, text="Enter Arabic text (or paste / load .docx):",
                            bg="#071024", fg="#cbd5e1", font=("Segoe UI", 11, "bold"))
        in_label.pack(anchor="w", padx=8, pady=(6, 0))

        self.input_text = tk.Text(in_frame, height=12, wrap=tk.WORD,
                                  font=("Segoe UI", 12), bg="#f6f8ff", fg="#071024", padx=8, pady=8)
        self.input_text.pack(fill=tk.X, padx=8, pady=8)

        # Controls row
        ctrl = tk.Frame(self.root, bg="#071024")
        ctrl.pack(fill=tk.X, padx=12, pady=(0, 8))

        self.translate_btn = tk.Button(ctrl, text="Translate", command=self.translate_async,
                                       bg="#ff7b7b", fg="white", font=("Segoe UI", 11, "bold"),
                                       state=tk.DISABLED, padx=14, pady=8)
        self.translate_btn.pack(side="left", padx=6)

        clear_btn = tk.Button(ctrl, text="Clear Input", command=self.clear_input,
                              bg="#6ee7b7", fg="#073b3a", font=("Segoe UI", 11),
                              padx=12, pady=8)
        clear_btn.pack(side="left", padx=6)

        load_btn = tk.Button(ctrl, text="Load .docx (optional)", command=self.load_docx,
                             bg="#8ec5ff", fg="#052d4d", font=("Segoe UI", 11), padx=12, pady=8)
        load_btn.pack(side="left", padx=6)

        save_btn = tk.Button(ctrl, text="Save Translation", command=self.save_translation,
                             bg="#ffd6a5", fg="#3d2f00", font=("Segoe UI", 11), padx=12, pady=8)
        save_btn.pack(side="right", padx=6)

        # Output area
        out_frame = tk.Frame(self.root, bg="#071024")
        out_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        out_label = tk.Label(out_frame, text="English translation:",
                             bg="#071024", fg="#cbd5e1", font=("Segoe UI", 11, "bold"))
        out_label.pack(anchor="w", padx=8, pady=(6, 0))

        self.output_text = tk.Text(out_frame, height=12, wrap=tk.WORD,
                                   font=("Segoe UI", 12), bg="#fffaf0", fg="#072029", padx=8, pady=8)
        self.output_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.output_text.insert("1.0", "Translation will appear here when ready.")
        self.output_text.config(state=tk.DISABLED)

        # Status bar
        self.status_label = tk.Label(self.root, text="Initializing...", anchor="w",
                                     bg="#0b1220", fg="#a3b2c7", font=("Segoe UI", 10), padx=8)
        self.status_label.pack(fill=tk.X, side=tk.BOTTOM)

    def set_status(self, text):
        def _update():
            self.status_label.config(text=text)
        self.root.after(0, _update)

    def load_model_async(self):
        """Load model in background thread. If local model folder empty, attempt download to cache then save."""
        def worker():
            try:
                self.set_status("Checking local model folder...")
                # If folder has expected files, load from local
                if self._local_model_present():
                    self.set_status("Loading model from local folder...")
                    self.tokenizer = MarianTokenizer.from_pretrained(self.model_folder, use_fast=False)
                    self.model = MarianMTModel.from_pretrained(self.model_folder)
                    self.model.to("cpu")
                    self.set_status("Model loaded from local folder. Ready.")
                    self.root.after(0, lambda: self.translate_btn.config(state=tk.NORMAL))
                    return

                # Else attempt to download (first run). Use cache_dir to save downloaded files.
                self.set_status("Local model not found. Attempting to download (first run needs internet)...")
                # This will download to transformers cache under cache_dir
                self.tokenizer = MarianTokenizer.from_pretrained(self.model_name, use_fast=False, cache_dir=self.model_cache_dir)
                self.model = MarianMTModel.from_pretrained(self.model_name, cache_dir=self.model_cache_dir)
                self.model.to("cpu")

                # Save a local copy to our model_folder for easy offline loading next time
                self.set_status("Saving model to local folder for offline use...")
                self.tokenizer.save_pretrained(self.model_folder)
                self.model.save_pretrained(self.model_folder)

                self.set_status("Model downloaded and saved locally. Ready.")
                self.root.after(0, lambda: self.translate_btn.config(state=tk.NORMAL))
            except Exception as exc:
                tb = traceback.format_exc()
                self.set_status("Model load error. See popup.")
                msg = (
                    "Failed to load or download the model.\n\n"
                    "Possible causes:\n"
                    "• No internet connection on first run (model must be downloaded once).\n"
                    "• Permission issues writing to C:\\Users\\intel\\models\n"
                    "• Missing dependencies (transformers, sentencepiece, torch)\n\n"
                    f"Error details:\n{exc}\n\nFull traceback printed to console."
                )
                print(tb)
                self.root.after(0, lambda: messagebox.showerror("Model Error", msg))
                # Keep translate button disabled
        threading.Thread(target=worker, daemon=True).start()

    def _local_model_present(self):
        """Check whether the local model folder looks like a valid pretrained model folder."""
        if not os.path.isdir(self.model_folder):
            return False
        existing = set(os.listdir(self.model_folder))
        # Basic checks
        if "config.json" in existing and ("pytorch_model.bin" in existing or any(f.endswith(".safetensors") for f in existing)):
            return True
        if "config.json" in existing and ("spiece.model" in existing or "vocab.json" in existing):
            return True
        return False

    def load_docx(self):
        if Document is None:
            messagebox.showwarning("Missing package", "python-docx not installed. Install with:\n\npip install python-docx")
            return
        filename = filedialog.askopenfilename(filetypes=[("Word Files", "*.docx")])
        if not filename:
            return
        try:
            doc = Document(filename)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip() != ""]
            text = "\n\n".join(paragraphs)
            self.input_text.delete("1.0", tk.END)
            self.input_text.insert("1.0", text)
            self.set_status(f"Loaded {os.path.basename(filename)} with {len(paragraphs)} paragraphs.")
        except Exception as e:
            messagebox.showerror("Load Error", f"Failed to load .docx: {e}")

    def clear_input(self):
        self.input_text.delete("1.0", tk.END)

    def save_translation(self):
        try:
            text = self.output_text.get("1.0", tk.END).strip()
            if not text:
                messagebox.showwarning("Nothing to save", "No translated text to save.")
                return
            fname = filedialog.asksaveasfilename(defaultextension=".txt",
                                                 filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                                                 initialfile=f"translation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
            if not fname:
                return
            with open(fname, "w", encoding="utf-8") as f:
                f.write(text)
            messagebox.showinfo("Saved", f"Saved translation to:\n{fname}")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))

    def translate_async(self):
        """Run translation in thread to keep GUI responsive."""
        if self.is_translating:
            return
        if self.model is None or self.tokenizer is None:
            messagebox.showwarning("Model not ready", "Model is not loaded yet. Wait until status says 'Ready'.")
            return
        text = self.input_text.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("No input", "Enter Arabic text to translate.")
            return

        def worker():
            try:
                self.is_translating = True
                self.set_status("Translating...")
                paragraphs = text.split("\n\n")
                translated_paragraphs = []
                max_input_len = getattr(self.model.config, "max_position_embeddings", 512)
                # create safe chunk size leaving room for special tokens and generation length
                chunk_size = max_input_len - 50 if max_input_len > 100 else 450

                for para in paragraphs:
                    if not para.strip():
                        translated_paragraphs.append("")
                        continue
                    # Tokenize to IDs to chunk if too long
                    input_ids = self.tokenizer.encode(para, add_special_tokens=True)
                    if len(input_ids) <= chunk_size:
                        # simple short paragraph
                        inputs = torch.tensor([input_ids])
                        with torch.no_grad():
                            out = self.model.generate(inputs, max_new_tokens=256, num_beams=4, early_stopping=True)
                        translated = self.tokenizer.decode(out[0], skip_special_tokens=True)
                        translated_paragraphs.append(translated)
                    else:
                        # chunk and translate piecewise
                        parts = []
                        start = 0
                        while start < len(input_ids):
                            chunk_ids = input_ids[start:start + chunk_size]
                            inputs = torch.tensor([chunk_ids])
                            with torch.no_grad():
                                out = self.model.generate(inputs, max_new_tokens=256, num_beams=4, early_stopping=True)
                            part = self.tokenizer.decode(out[0], skip_special_tokens=True)
                            parts.append(part)
                            start += chunk_size
                        # join parts with space (best-effort)
                        translated_paragraphs.append(" ".join(parts))

                final = "\n\n".join(translated_paragraphs)
                # show result in GUI
                self.root.after(0, lambda: self.show_translation(final))
            except Exception as e:
                tb = traceback.format_exc()
                print(tb)
                self.root.after(0, lambda: messagebox.showerror("Translation error", f"{e}\n\nSee console for traceback."))
                self.set_status("Translation failed.")
            finally:
                self.is_translating = False

        threading.Thread(target=worker, daemon=True).start()

    def show_translation(self, text):
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert("1.0", text)
        self.output_text.config(state=tk.DISABLED)
        self.set_status("Translation complete.")

if __name__ == "__main__":
    root = tk.Tk()
    app = ArabicToEnglishGUI(root)
    root.mainloop()
