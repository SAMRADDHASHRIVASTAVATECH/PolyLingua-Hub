import os
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
from datetime import datetime
import torch
from docx import Document

# transformers imports are done inside loader function to gracefully handle fallback
from transformers import MarianMTModel, MarianTokenizer, T5ForConditionalGeneration, T5Tokenizer

class PTtoENTranslatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Portuguese → English Translator")
        self.root.geometry("950x650")
        self.root.configure(bg="#1a1a2e")

        # Primary model (Marian pt->en). Fallback: small T5 pt->en
        self.primary_model_name = "geralt/Opus-mt-pt-en"
        self.fallback_model_name = "manueldeprada/t5-small-pt-en"

        self.model = None
        self.tokenizer = None
        self.model_type = None  # 'marian' or 't5'
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_translating = False

        self.build_gui()
        self.load_model_async()

    def build_gui(self):
        header = tk.Label(self.root, text="🇵🇹 Portuguese → English", font=("Helvetica", 22, "bold"),
                          bg="#162447", fg="#e43f5a", pady=12)
        header.pack(fill=tk.X)

        # Input
        in_frame = tk.Frame(self.root, bg="#1f4068")
        in_frame.pack(fill=tk.X, padx=24, pady=(16,8))
        tk.Label(in_frame, text="Enter Portuguese text or paste content:",
                 bg="#1f4068", fg="#e0e0e0", font=("Helvetica", 11, "bold")).pack(anchor="w", padx=8, pady=(6,0))
        self.input_text = tk.Text(in_frame, height=10, font=("Helvetica", 12), wrap=tk.WORD,
                                  bg="#e0e0e0", fg="#1f4068", padx=10, pady=10, relief="flat")
        self.input_text.pack(fill=tk.X, padx=8, pady=10)

        # Buttons
        btn_frame = tk.Frame(self.root, bg="#1a1a2e")
        btn_frame.pack(fill=tk.X, padx=24, pady=(0,18))
        self.translate_btn = tk.Button(btn_frame, text="Translate", bg="#e43f5a", fg="white",
                                       font=("Helvetica", 12, "bold"), padx=20, pady=8,
                                       command=self.translate_async, state=tk.DISABLED)
        self.translate_btn.pack(side="left", padx=8)
        tk.Button(btn_frame, text="Clear Input", bg="#0f3460", fg="white",
                  font=("Helvetica", 12, "bold"), command=self.clear_input).pack(side="left", padx=8)
        tk.Button(btn_frame, text="Load .docx", bg="#0f3460", fg="white",
                  font=("Helvetica", 12, "bold"), command=self.load_docx).pack(side="left", padx=8)
        tk.Button(btn_frame, text="Save Translation", bg="#0f3460", fg="white",
                  font=("Helvetica", 12, "bold"), command=self.save_translation).pack(side="right", padx=8)

        # Output
        out_frame = tk.Frame(self.root, bg="#1f4068")
        out_frame.pack(fill=tk.BOTH, expand=True, padx=24, pady=(0,18))
        tk.Label(out_frame, text="English Translation:",
                 bg="#1f4068", fg="#e0e0e0", font=("Helvetica", 11, "bold")).pack(anchor="w", padx=8, pady=(6,0))
        self.output_text = tk.Text(out_frame, height=12, font=("Helvetica", 12), wrap=tk.WORD,
                                   bg="#e0e0e0", fg="#1f4068", padx=10, pady=10, relief="flat")
        self.output_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=10)
        self.output_text.insert("1.0", "Translation will appear here...")
        self.output_text.config(state="disabled")

        # Status
        self.status_label = tk.Label(self.root, text="Loading model...", bg="#1a1a2e",
                                     fg="#00adb5", font=("Helvetica", 10))
        self.status_label.pack(side="bottom", fill=tk.X)

    def load_docx(self):
        filename = filedialog.askopenfilename(filetypes=[("Word files","*.docx")])
        if not filename:
            return
        try:
            doc = Document(filename)
            text = "\n\n".join([p.text for p in doc.paragraphs])
            self.input_text.delete("1.0", "end")
            self.input_text.insert("1.0", text.strip())
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read .docx: {e}")

    def load_model_async(self):
        def _load():
            try:
                self.update_status(f"Loading primary model: {self.primary_model_name} ...")
                # try primary (Marian)
                self.tokenizer = MarianTokenizer.from_pretrained(self.primary_model_name)
                self.model = MarianMTModel.from_pretrained(self.primary_model_name)
                self.model.to(self.device)
                self.model_type = "marian"
                self.root.after(0, self.on_model_loaded)
            except Exception as primary_err:
                # fallback to T5
                try:
                    self.update_status(f"Primary failed, loading fallback: {self.fallback_model_name} ...")
                    self.tokenizer = T5Tokenizer.from_pretrained(self.fallback_model_name)
                    self.model = T5ForConditionalGeneration.from_pretrained(self.fallback_model_name)
                    self.model.to(self.device)
                    self.model_type = "t5"
                    self.root.after(0, self.on_model_loaded)
                except Exception as fallback_err:
                    err_msg = f"Primary error: {primary_err}\n\nFallback error: {fallback_err}"
                    self.root.after(0, lambda: self.model_error(err_msg))

        threading.Thread(target=_load, daemon=True).start()

    def on_model_loaded(self):
        self.update_status(f"Model loaded ({self.model_type}) — ready.")
        self.translate_btn.config(state="normal")

    def model_error(self, error):
        self.update_status("Model load failed.")
        messagebox.showerror("Model load error", f"Could not load models:\n\n{error}")

    def translate_async(self):
        if self.is_translating or self.model is None:
            return
        src_text = self.input_text.get("1.0","end").strip()
        if not src_text:
            messagebox.showwarning("Empty input", "Please enter Portuguese text to translate.")
            return

        def _translate():
            try:
                self.is_translating = True
                self.update_status("Translating...")
                paras = [p for p in src_text.split("\n\n")]
                out_paras = []

                for para in paras:
                    if not para.strip():
                        out_paras.append("")
                        continue

                    if self.model_type == "marian":
                        # Marian: straightforward pt->en
                        inputs = self.tokenizer(para, return_tensors="pt", truncation=True, padding=True)
                        for k,v in inputs.items():
                            inputs[k] = v.to(self.device)
                        gen = self.model.generate(**inputs, max_length=512)
                        txt = self.tokenizer.decode(gen[0], skip_special_tokens=True)
                        out_paras.append(txt)
                    else:
                        # T5 fallback: prefix not required if fine-tuned; if needed add "translate pt to en: "
                        prefix = ""  # if model requires, set e.g. "translate pt to en: "
                        text_in = prefix + para
                        inputs = self.tokenizer(text_in, return_tensors="pt", truncation=True, padding=True, max_length=512)
                        for k,v in inputs.items():
                            inputs[k] = v.to(self.device)
                        gen = self.model.generate(**inputs, max_length=512)
                        txt = self.tokenizer.decode(gen[0], skip_special_tokens=True)
                        out_paras.append(txt)

                result = "\n\n".join(out_paras)
                self.root.after(0, lambda: self.show_translation(result))
            except Exception as e:
                self.root.after(0, lambda: self.translation_error(str(e)))
            finally:
                self.is_translating = False

        threading.Thread(target=_translate, daemon=True).start()

    def show_translation(self, text):
        self.output_text.config(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", text)
        self.output_text.config(state="disabled")
        self.update_status("Translation complete.")

    def translation_error(self, e):
        self.update_status("Translation failed.")
        messagebox.showerror("Translation error", e)

    def clear_input(self):
        self.input_text.delete("1.0", "end")

    def save_translation(self):
        txt = self.output_text.get("1.0","end").strip()
        if not txt:
            messagebox.showwarning("Nothing to save", "No translation available.")
            return
        fn = filedialog.asksaveasfilename(defaultextension=".txt",
                                          filetypes=[("Text","*.txt"),("All","*.*")],
                                          initialfile=f"translation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        if fn:
            with open(fn, "w", encoding="utf-8") as f:
                f.write(txt)
            messagebox.showinfo("Saved", f"Saved as {os.path.basename(fn)}")

    def update_status(self, msg):
        self.status_label.config(text=msg)

if __name__ == "__main__":
    root = tk.Tk()
    app = PTtoENTranslatorGUI(root)
    root.mainloop()
