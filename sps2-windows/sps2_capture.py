import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import threading, time, shutil, hashlib, json, datetime

class Capture:
    def __init__(self, root):
        self.root=root; root.title("SPS2 Cache Capture"); root.geometry("780x490")
        self.running=False; self.seen={}
        self.source=tk.StringVar(value=str(Path.home() / "AppData" / "Local"))
        self.dest=tk.StringVar(value=str(Path.home() / "Documents" / "SPS2_Captures"))
        for title,var in [("Cache directory to monitor",self.source),("Capture destination",self.dest)]:
            ttk.Label(root,text=title).pack(anchor="w",padx=12,pady=(12,2))
            frame=ttk.Frame(root);frame.pack(fill="x",padx=12)
            ttk.Entry(frame,textvariable=var).pack(side="left",fill="x",expand=True)
            ttk.Button(frame,text="Browse",command=lambda v=var:v.set(filedialog.askdirectory() or v.get())).pack(side="left")
        bar=ttk.Frame(root);bar.pack(pady=12)
        self.start=ttk.Button(bar,text="Start Capture",command=self.begin);self.start.pack(side="left",padx=8)
        self.stop=ttk.Button(bar,text="Stop",command=self.end,state="disabled");self.stop.pack(side="left")
        self.log=tk.Text(root,height=17);self.log.pack(fill="both",expand=True,padx=12,pady=8)
        ttk.Label(root,text="Monitor only a specific SPS2 cache folder. Files are copied, never modified.").pack(pady=5)
        root.protocol("WM_DELETE_WINDOW",self.close)
    def say(self,msg):
        self.root.after(0,lambda:self._say(msg))
    def _say(self,msg):
        self.log.insert("end",msg+"\n");self.log.see("end")
    def begin(self):
        src=Path(self.source.get()).resolve();dst=Path(self.dest.get()).resolve()
        if not src.is_dir():messagebox.showerror("Invalid folder","Select an existing source directory.");return
        if src==dst or src in dst.parents or dst in src.parents:
            messagebox.showerror("Invalid folders","Source and destination must not contain one another.");return
        dst.mkdir(parents=True,exist_ok=True)
        self.running=True;self.start.configure(state="disabled");self.stop.configure(state="normal")
        threading.Thread(target=self.scan,args=(src,dst),daemon=True).start()
        self.say("Monitoring "+str(src))
    def scan(self,src,dst):
        while self.running:
            try:
                for p in src.rglob("*"):
                    if not self.running:break
                    if not p.is_file() or p.is_symlink():continue
                    try:
                        stat=p.stat();key=str(p);signature=(stat.st_size,stat.st_mtime_ns)
                        if self.seen.get(key)==signature:continue
                        self.seen[key]=signature
                        if not stat.st_size:continue
                        rel=p.relative_to(src)
                        target=dst/rel;target.parent.mkdir(parents=True,exist_ok=True)
                        temp=target.with_name(target.name+".partial")
                        shutil.copy2(p,temp)
                        if p.stat().st_size!=stat.st_size:
                            temp.unlink(missing_ok=True);self.seen.pop(key,None);continue
                        digest=hashlib.sha256(temp.read_bytes()).hexdigest()
                        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
                            target=target.with_name(target.stem+"_"+digest[:12]+target.suffix)
                        temp.replace(target)
                        record={"captured_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"source":str(p),"saved":str(target),"bytes":stat.st_size,"sha256":digest}
                        with (dst/"manifest.jsonl").open("a",encoding="utf-8") as f:f.write(json.dumps(record)+"\n")
                        self.say("Saved "+str(rel))
                    except (OSError,PermissionError) as e:self.say("Skipped "+str(p)+": "+str(e))
            except OSError as e:self.say("Scan error: "+str(e))
            for _ in range(20):
                if not self.running:break
                time.sleep(.1)
        self.say("Stopped.")
    def end(self):
        self.running=False;self.start.configure(state="normal");self.stop.configure(state="disabled")
    def close(self):
        self.running=False;self.root.destroy()
if __name__=="__main__":
    root=tk.Tk();Capture(root);root.mainloop()
