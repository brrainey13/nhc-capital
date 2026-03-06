---
title: How Computers Actually Work
summary: 'A guide for smart people who never studied computer science.'
read_when:
  - Learning fundamentals of how software and hardware interact
---

# How Computers Actually Work

**A guide for smart people who never studied computer science.**

You're an accountant. You understand ledgers, reconciliation, audits, and systems that have to be *right*. That's actually perfect preparation for understanding computers — because computers are just very fast, very stupid accountants.

This guide has two parts:

1. **The 90-Minute Reality Check** — a fast walkthrough you can finish in a sitting
2. **The 30-Day Deep Path** — a weekly plan if you want to go further

No fluff. No jargon without explanation. Real terminal commands you can run right now.

---

# Part 1 — The 90-Minute Reality Check

---

## 1. What Information Is

**Why this matters:** Every single thing a computer does — every spreadsheet, every email, every video call — is just information being stored, moved, or transformed. If you understand what information *is* to a computer, everything else clicks.

A **bit** is the smallest unit of information. It's a yes or no. A 1 or a 0. Think of it as a single cell in a spreadsheet that can only hold `TRUE` or `FALSE`.

A **byte** is 8 bits grouped together. Why 8? Historical convention, but it works out nicely: 8 bits gives you 256 possible combinations (2⁸ = 256), which is enough to represent every letter, digit, and symbol you'd ever type.

Think of it this way:
- **Bit** = one light switch (on/off)
- **Byte** = a row of 8 light switches (256 possible patterns)
- **Kilobyte (KB)** = ~1,000 bytes ≈ a short email
- **Megabyte (MB)** = ~1,000,000 bytes ≈ a photo
- **Gigabyte (GB)** = ~1,000,000,000 bytes ≈ a movie
- **Terabyte (TB)** = ~1,000 GB ≈ a small company's entire file server

### 🧪 Terminal Experiment

```bash
# Let's see how a computer stores the word "Hello"
echo -n "Hello" | xxd
```

You'll see something like:
```
00000000: 4865 6c6c 6f                             Hello
```

Each pair of characters (`48`, `65`, `6c`, `6c`, `6f`) is one byte written in hexadecimal (we'll cover that next). The letter "H" is stored as the number 72 (which is `48` in hex). That's it. Every letter is just a number.

### 💡 Mental Model

> A computer doesn't know what a "letter" or a "photo" or a "song" is. It only knows numbers. Everything — *everything* — is numbers. The software decides what those numbers *mean*.

---

## 2. Why Computers Use Binary

**Why this matters:** People always ask "why not just use normal numbers?" There's a beautifully practical reason.

Imagine you're designing a machine that needs to be reliable. You could build it to distinguish between 10 different voltage levels (0-9, like our decimal system), but that's *hard*. Electrical noise, temperature changes, manufacturing imperfections — any of those could make the machine confuse a 6 for a 7.

Or you could build it to distinguish between just TWO states: electricity flowing, or not. High voltage, or low. That's *easy* to get right. Even a cheap, imperfect circuit can reliably tell the difference between "on" and "off."

That's why binary won. Not because it's mathematically elegant (though it is), but because it's **electrically reliable**. It's the accounting equivalent of using only checkmarks and blanks instead of trying to write tiny numbers in each cell.

### 🧪 Terminal Experiment

```bash
# Convert the number 42 to binary
echo "obase=2; 42" | bc
```

Output: `101010`

That means: 32 + 8 + 2 = 42. Each position is a power of 2 (just like each position in decimal is a power of 10).

```bash
# And back to decimal
echo "ibase=2; 101010" | bc
```

Output: `42`

### 💡 Mental Model

> Binary isn't a computer being difficult. It's a computer being practical. Two states are easy to build reliably. Everything else is software making those two states *useful*.

---

## 3. Numbers: Binary, Hex, and Floating Point

**Why this matters:** You'll encounter these three number representations constantly. You don't need to do conversions in your head — you just need to know *why* each one exists.

**Binary (base 2):** What the computer actually uses internally. Only digits 0 and 1.

**Hexadecimal / "hex" (base 16):** A shorthand for binary that humans find easier to read. Uses digits 0–9 plus A–F. Every hex digit represents exactly 4 bits, so one byte is always exactly 2 hex digits. That's why colors in web design look like `#FF5733` — each pair is a byte controlling red, green, or blue.

| Decimal | Binary   | Hex |
|---------|----------|-----|
| 0       | 0000     | 0   |
| 9       | 1001     | 9   |
| 10      | 1010     | A   |
| 15      | 1111     | F   |
| 255     | 11111111 | FF  |

**Floating point:** How computers handle decimal numbers (like $19.99). Here's the uncomfortable truth: computers *cannot perfectly represent most decimals*. The number 0.1 in a computer is actually 0.1000000000000000055511151231257827021181583404541015625. This is why financial software uses special "decimal" types instead of floating point — and why your accounting software sometimes shows a penny off.

### 🧪 Terminal Experiment

```bash
# The famous floating point problem
python3 -c "print(0.1 + 0.2)"
```

Output: `0.30000000000000004`

Not 0.3. This isn't a bug — it's a fundamental limitation of how computers store decimals in binary. It's like trying to write ⅓ in decimal: 0.333333... you can never finish.

```bash
# How accountants fix it (use Decimal type)
python3 -c "from decimal import Decimal; print(Decimal('0.1') + Decimal('0.2'))"
```

Output: `0.3` ✓

### 💡 Mental Model

> Hex is just a more readable way to write binary — like using abbreviations. Floating point is the computer's imperfect attempt at decimals — which is why real financial systems never use it for money.

---

## 4. Memory vs Disk

**Why this matters:** This is one of the most practically important distinctions in computing, and it maps perfectly to something you already understand.

**Memory (RAM)** is your desk. It's where you spread out the papers you're actively working on. It's fast to access, but limited in size, and it gets cleared when you leave (turn off the computer).

**Disk (SSD/Hard Drive)** is your filing cabinet. It holds everything — even when the power's off — but it's slower to retrieve things from. You have to get up, walk over, pull out the file, and bring it back to your desk.

| | RAM (Memory) | Disk (Storage) |
|---|---|---|
| **Analogy** | Your desk | Filing cabinet |
| **Speed** | ~100x faster | Slower |
| **Survives power off?** | No | Yes |
| **Typical size** | 8–64 GB | 256 GB – 2 TB |
| **Cost per GB** | ~$3 | ~$0.10 |
| **What it holds** | Currently running programs + their data | Files, apps, OS |

When you "open" a file, the computer copies it from disk into memory. When you "save," it copies from memory back to disk. If you lose power before saving — the memory version (your desk) is gone. The last-saved disk version (filing cabinet) survives.

### 🧪 Terminal Experiment

```bash
# How much memory (RAM) do you have?
sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f GB RAM\n", $1/1073741824}' || free -h 2>/dev/null | head -2
```

```bash
# How much disk space?
df -h / | tail -1 | awk '{print "Disk: " $2 " total, " $4 " available"}'
```

```bash
# Watch memory usage in real time (press q to quit)
top -l 1 | head -12
```

### 💡 Mental Model

> RAM is your desk (fast, temporary, limited). Disk is your filing cabinet (slower, permanent, spacious). Every program constantly shuffles data between the two.

---

## 5. What a CPU Does

**Why this matters:** The CPU is the computer. Everything else is support staff. Understanding what it does (and what it *can't* do) demystifies every performance question you'll ever have.

CPU stands for Central Processing Unit. It is absurdly simple in concept: it reads an instruction, executes it, and moves to the next one. That's it. It does this a few *billion* times per second.

Each instruction is tiny:
- Add these two numbers
- Compare this number to zero
- Copy this value from here to there
- If that comparison was true, jump to instruction #4072 instead of the next one

That's essentially the complete list. There is no "send email" instruction or "calculate tax" instruction. Every complex thing a computer does is built from billions of these trivial steps.

Think of the CPU as an incredibly fast but completely literal clerk. If you hand them a 10,000-step procedure written with perfect precision, they'll execute it flawlessly at superhuman speed. But they cannot improvise, infer, or skip steps. They can't even tell if the instructions make sense.

**Clock speed** (like 3.2 GHz) means 3.2 billion cycles per second. Each instruction takes one or a few cycles.

**Cores** are like having multiple clerks. A 4-core CPU can do 4 things simultaneously.

### 🧪 Terminal Experiment

```bash
# What CPU do you have?
sysctl -n machdep.cpu.brand_string 2>/dev/null || cat /proc/cpuinfo 2>/dev/null | grep "model name" | head -1
```

```bash
# How many cores?
sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null
```

```bash
# Watch your CPU work in real time — each process is a running program
# (press q to quit)
top -l 1 | head -20
```

### 💡 Mental Model

> A CPU is a clerk that follows instructions one at a time, billions of times per second. It's not smart — it's *fast*. All software is just a very long list of very simple instructions.

---

## 6. What Code Actually Is

**Why this matters:** "Code" sounds mystical. It's not. It's just instructions written in a way that eventually becomes the simple steps your CPU can follow.

Imagine you have a new employee who's extremely literal-minded (the CPU). You can't say "handle the invoices." You have to write out every step:

```
1. Open the inbox
2. Look at the first email
3. If it contains an attachment ending in .pdf:
   a. Download the attachment
   b. Read the dollar amount from line 3
   c. Add it to the running total
   d. Move email to "Processed" folder
4. If not, skip it
5. Move to the next email
6. If there are more emails, go to step 2
7. Otherwise, print the total
```

That's code. It's a recipe. Different programming languages are just different ways of writing the same recipe:

**Python** (reads almost like English):
```python
total = 0
for email in inbox:
    if email.attachment.endswith('.pdf'):
        amount = read_amount(email.attachment)
        total = total + amount
print(total)
```

**C** (closer to what the CPU actually sees):
```c
int total = 0;
for (int i = 0; i < inbox_count; i++) {
    if (ends_with(inbox[i].attachment, ".pdf")) {
        total += read_amount(inbox[i].attachment);
    }
}
printf("%d\n", total);
```

The computer can't run Python or C directly. A **compiler** or **interpreter** translates the human-readable code into the tiny CPU instructions from the last section. It's like having a translator turn your English procedures manual into the clerk's native language.

### 🧪 Terminal Experiment

```bash
# Write a tiny program and run it — right now
python3 -c "
revenue = 50000
expenses = 32000
profit = revenue - expenses
tax_rate = 0.21
tax = profit * tax_rate
print(f'Revenue:  \${revenue:,}')
print(f'Expenses: \${expenses:,}')
print(f'Profit:   \${profit:,}')
print(f'Tax (21%): \${tax:,.2f}')
print(f'Net:      \${profit - tax:,.2f}')
"
```

You just wrote and ran a program. That's genuinely all there is to it.

### 💡 Mental Model

> Code is a recipe written for an extremely literal, extremely fast cook. Programming languages exist to let humans write recipes in something closer to English. The computer translates it down to its own simple steps.

---

## 7. What an Operating System Does

**Why this matters:** The operating system (macOS, Windows, Linux) is the layer between your programs and the actual hardware. Without it, every program would need to know how to talk to your specific keyboard, screen, disk, and network card. That would be insane.

Think of the OS as the **office manager** for your computer:

**1. Resource allocation (who gets what):**
Your computer has limited RAM, CPU time, and disk space. Multiple programs want them simultaneously. The OS divides resources fairly — like an office manager deciding who gets the conference room and when. Your browser, email, and Spotify are all running "at once," but the OS is actually giving each one tiny slices of CPU time so fast you can't tell they're taking turns.

**2. Hardware abstraction (one interface for everything):**
When your Python script says "open this file," it doesn't need to know if you have a Samsung SSD or a Western Digital hard drive. The OS handles that. It's like how you submit a purchase order to the office manager — you don't need to know which vendor they use.

**3. Security (keeping programs separated):**
Each program gets its own walled-off section of memory. Your browser can't read your banking app's memory. If a program crashes, it doesn't take down everything else. The OS is the bouncer.

**4. File system (organizing the filing cabinet):**
The OS creates the illusion of folders and files. The disk itself is just a giant array of numbered slots. The OS maintains a directory (like a chart of accounts) mapping names to locations.

### 🧪 Terminal Experiment

```bash
# See every program currently running (there are more than you think)
ps aux | wc -l
```

```bash
# See the top memory consumers
ps aux --sort=-%mem 2>/dev/null | head -10 || ps aux -m | head -10
```

```bash
# See your file system — the OS's directory structure
ls -la /
```

Those top-level folders (`/Users`, `/System`, `/Applications`, etc.) are the OS organizing everything into a structure. Under the hood, it's all just numbered bytes on a disk.

### 💡 Mental Model

> The operating system is the office manager. It allocates resources, provides a consistent interface to hardware, keeps programs from interfering with each other, and organizes storage. Without it, every program would have to manage everything itself.

---

## 8. What the Internet Actually Is

**Why this matters:** The internet isn't magic or "the cloud." It's computers sending messages to each other over wires (and sometimes radio waves). That's it.

**The physical reality:** The internet is literally cables — mostly fiber optic cables, including massive ones running along ocean floors between continents. When you load a website, light pulses (representing 1s and 0s) are shooting through glass fibers at near the speed of light.

**IP addresses:** Every device on the internet has an address, like a mailing address. It looks like `142.250.80.46` (that's Google). When you type "google.com," your computer first asks a **DNS server** (like a phone book) "what's the IP address for google.com?"

**How a request works — the postal analogy:**

1. You type `google.com` in your browser
2. Your computer looks up the IP address (DNS = phone book)
3. Your computer creates a message: "Send me your homepage"
4. The message is split into **packets** (like cutting a long letter into numbered postcards)
5. Each packet is stamped with the destination IP and your return IP
6. Packets hop through multiple routers (like post offices) to reach Google
7. Google's computer sends back packets with the webpage content
8. Your browser reassembles the packets and displays the page

This whole round trip typically takes 20–100 milliseconds. That's one-tenth to one-half of an eye blink.

**HTTP** is the language browsers and servers use to talk. It's remarkably simple:
- Browser sends: `GET /search?q=accounting HTTP/1.1`
- Server sends back: `200 OK` + the page content

### 🧪 Terminal Experiment

```bash
# Look up a domain name (DNS query — the phone book step)
nslookup google.com
```

```bash
# Trace the route packets take from your computer to Google
# Each line is a "hop" — a router your data passes through
traceroute -m 15 google.com 2>/dev/null || traceroute google.com
```

```bash
# Make an actual HTTP request (what your browser does behind the scenes)
curl -s -I https://google.com | head -10
```

That `HTTP/1.1 301` or `200` response? That's Google's server talking directly to your computer. Your browser just makes it pretty.

### 💡 Mental Model

> The internet is computers sending numbered postcards to each other over wires. DNS is the phone book. Routers are post offices. HTTP is the language. "The cloud" is just other people's computers.

---

## 9. What a Server Is

**Why this matters:** A "server" sounds like a special, expensive thing. It's not. It's just a computer that waits for requests and sends back responses. Your laptop could be a server right now.

Remember the CPU section? A server is exactly the same hardware — processor, memory, disk — just configured to answer requests from other computers instead of showing a desktop to a human sitting in front of it.

When someone says "our data is on the server," they mean "our data is on a computer in a data center somewhere that's always turned on and connected to the internet."

**A restaurant analogy:**
- **Your laptop** = eating at home (you cook for yourself)
- **A server** = a restaurant kitchen (cooks for anyone who orders)
- **The internet** = the road between you and the restaurant
- **HTTP request** = your order
- **HTTP response** = your food

**"The cloud" (AWS, Google Cloud, Azure):** Instead of buying your own server hardware, you rent someone else's. It's like renting office space instead of buying a building. Amazon, Google, and Microsoft have millions of servers in massive data centers. You pay by the hour to use them.

When you use Google Sheets, here's what's really happening:
1. Your browser sends a request over the internet to Google's servers
2. Google's server runs code that reads your spreadsheet data from its disk
3. The server sends back HTML/JavaScript to your browser
4. Your browser displays it
5. When you edit a cell, your browser sends the change back to the server
6. The server saves it to disk

That's it. That's "cloud computing."

### 🧪 Terminal Experiment

```bash
# Start a server on your own computer (yes, really)
# This makes your machine a server for 5 seconds
python3 -c "
import http.server
import threading
import urllib.request

server = http.server.HTTPServer(('localhost', 8888), http.server.SimpleHTTPRequestHandler)
t = threading.Thread(target=server.handle_request)
t.start()

# Now request something from your own server
response = urllib.request.urlopen('http://localhost:8888')
print('Status:', response.status)
print('Your computer just served a web page to itself!')
server.server_close()
"
```

### 💡 Mental Model

> A server is just a computer that answers requests. "The cloud" is renting someone else's servers. There's no magic — it's the same CPUs, memory, and disks we already discussed, just in a data center instead of on your desk.

---

## 10. Where AI Tools Fit (and Where They Don't)

**Why this matters:** AI is the most hyped and least understood technology in business right now. With what you've learned in the last 9 sections, you can now understand what it actually is — and isn't.

**What AI (specifically large language models like ChatGPT) actually is:**

It's a program. It runs on servers. Those servers have CPUs (and specialized chips called GPUs), memory, and disks — exactly what we discussed. There is nothing metaphysically different about AI software.

The "intelligence" is a very large mathematical function (a "model") with billions of numerical parameters that were tuned by processing enormous amounts of text. When you ask it a question:

1. Your text is converted to numbers (remember — everything is numbers)
2. Those numbers are fed through the mathematical function
3. The function produces output numbers
4. Those numbers are converted back to text

It's not "thinking." It's an extremely sophisticated pattern-matching machine that produces statistically likely next words. It's like autocomplete on your phone, but trained on most of the internet and scaled up by a factor of a million.

**Where AI tools are genuinely useful:**
- Drafting text (emails, summaries, first drafts)
- Explaining concepts (like this guide could partially be)
- Searching/synthesizing information
- Writing and debugging code
- Pattern recognition in data

**Where they fail (and this matters for accounting):**
- **Arithmetic.** LLMs regularly get math wrong. Never trust an LLM to calculate your taxes.
- **Facts.** They generate plausible-sounding text, not verified facts. They "hallucinate."
- **Consistency.** Ask the same question twice, get different answers.
- **Auditing.** There's no audit trail. You can't trace *why* it gave an answer.
- **Confidentiality.** Anything you paste into a cloud AI may be stored or used for training.

**The accountant's rule of thumb:** Use AI like a smart intern. Good for first drafts and brainstorming. Never trust it for final numbers. Always verify. Never give it data you wouldn't give an intern.

### 🧪 Terminal Experiment

```bash
# AI models work with "tokens" — pieces of words, converted to numbers
# Here's a simple demonstration of how text becomes numbers
python3 -c "
text = 'The total revenue was \$50,000'
# Every character has a numeric code
for char in text:
    print(f'{char!r:6} → {ord(char):5d}')
print()
print('AI models use similar (but more complex) number encodings.')
print('The model itself is just math on those numbers.')
"
```

### 💡 Mental Model

> AI is software running on normal computers. It's an incredibly powerful pattern-matching machine, not a thinking entity. Use it like a smart but unreliable intern: great for drafts, dangerous for numbers, never the final authority.

---

# Part 2 — The 30-Day Deep Path

Now that you have the big picture, here's how to go deeper — at a comfortable pace. Budget about 30–45 minutes per day, mostly reading with some terminal exploration.

---

## Week 1: Information, Numbers, and Memory

### Core Idea
Everything in a computer is stored as patterns of bits. Understanding *how* is the foundation for understanding everything else. This week, you become fluent in the language computers speak.

### Why It Matters
When someone says "that file is 4 MB" or "we need more RAM" or "it's a 64-bit system," you'll know exactly what that means — and why it matters for cost, performance, and reliability.

### What to Read / Think About

- **Character encoding:** How does the computer store the letter "é" or a Chinese character or an emoji? Look up ASCII (the original, English-only system) and UTF-8 (the modern, everything system). Key insight: UTF-8 is backwards-compatible with ASCII — clever engineering.

- **How images work:** A photo is a grid of pixels. Each pixel is 3 numbers (red, green, blue), each 0–255 (one byte). A 1920×1080 image = 1920 × 1080 × 3 = ~6.2 million bytes = ~6 MB uncompressed. Compression (JPEG) makes it smaller by throwing away detail your eyes won't notice.

- **How sound works:** Sound is captured as thousands of number samples per second (44,100 per second for CD quality). Each sample is the amplitude of the sound wave at that instant.

- Read: The first two chapters of *Code* by Charles Petzold — the best book ever written on this topic. Available at most libraries.

### Terminal Experiments

```bash
# See the raw bytes of a file (any file!)
xxd /etc/hosts | head -20

# See how many bytes different types of content take
echo -n "Hello" | wc -c           # 5 bytes (one per letter)
echo -n "Hello 🌍" | wc -c        # 9 bytes (emoji takes 4 bytes in UTF-8!)

# Create a tiny image from raw numbers with Python
python3 -c "
# A 3x3 image where each pixel is (R, G, B)
# This creates a tiny PPM image file
with open('/tmp/tiny.ppm', 'w') as f:
    f.write('P3\n3 3\n255\n')
    f.write('255 0 0  0 255 0  0 0 255\n')   # Red, Green, Blue
    f.write('255 255 0  255 0 255  0 255 255\n')  # Yellow, Magenta, Cyan
    f.write('0 0 0  128 128 128  255 255 255\n')  # Black, Gray, White
print('Created /tmp/tiny.ppm — open it in Preview or any image viewer')
print('It is literally just a text file full of numbers.')
"
cat /tmp/tiny.ppm

# How does your computer decide how much memory to give a number?
python3 -c "
import sys
print(f'Small int (42):     {sys.getsizeof(42)} bytes')
print(f'Big int (10**100):  {sys.getsizeof(10**100)} bytes')
print(f'Float (3.14):       {sys.getsizeof(3.14)} bytes')
print(f'String (\"hello\"):   {sys.getsizeof(\"hello\")} bytes')
"
```

---

## Week 2: CPU, Assembly Intuition, and C as a Microscope

### Core Idea
The CPU is a machine that executes hilariously simple instructions at incomprehensible speed. Understanding this layer — even superficially — transforms your mental model from "computers are magic" to "computers are fast clerks."

### Why It Matters
When software is "slow," it's because too many instructions are being executed, or the CPU is waiting for data from slow memory/disk. When someone says "optimize," they mean "do the same job with fewer instructions or less waiting." This is directly analogous to process improvement in operations.

### What to Read / Think About

- **Assembly language:** You won't write it, but seeing it once is illuminating. Assembly is the human-readable version of what the CPU actually executes. Each line is one instruction: `ADD`, `MOV`, `CMP`, `JMP`. That's really all a computer can do.

- **C programming language:** C was invented in the 1970s and is still the language operating systems are written in. It's worth seeing because it maps almost directly to what the CPU does — it's a thin layer of convenience over assembly. Python, by contrast, is a thick layer of convenience.

- **The speed hierarchy:** CPU registers (instant) → L1 cache (1ns) → L2 cache (4ns) → RAM (100ns) → SSD (100,000ns) → Network (10,000,000ns). That's a range of 10 million to 1. It's like the difference between grabbing a pen from your pocket vs. ordering one from overseas.

- Read: *But How Do It Know?* by J. Clark Scott — builds a simple computer from scratch conceptually.

### Terminal Experiments

```bash
# See actual assembly language — what the CPU reads
# This compiles a tiny C program and shows the assembly
cat << 'EOF' > /tmp/add.c
int add(int a, int b) {
    return a + b;
}
EOF
cc -S -O0 /tmp/add.c -o /tmp/add.s 2>/dev/null && cat /tmp/add.s
# Each line is one CPU instruction. "add" becomes a single ADD instruction.

# See how fast your CPU actually is
python3 -c "
import time
count = 10_000_000
start = time.time()
total = 0
for i in range(count):
    total += i
elapsed = time.time() - start
print(f'Added {count:,} numbers in {elapsed:.2f} seconds')
print(f'That is {count/elapsed:,.0f} additions per second')
print(f'(And Python is ~100x slower than C — imagine C speed)')
"

# See your CPU's capabilities
sysctl -a 2>/dev/null | grep -i "cpu\.\|hw\.cpu" | head -20
```

---

## Week 3: Operating Systems, Processes, and Threads

### Core Idea
The operating system is the most important program on your computer. It's the invisible manager that lets dozens of programs share one CPU, protects them from each other, and provides a universal interface to hardware. Understanding processes and threads explains *how* your computer does many things "at once."

### Why It Matters
Every time you wonder "why is my computer slow?", "why did that app freeze?", or "is it safe to force-quit this?" — you're asking operating system questions. This week answers them.

### What to Read / Think About

- **Processes:** Each running program is a "process." It gets its own private memory space (like each department having its own locked file room). The OS rapidly switches between processes — giving each a tiny slice of CPU time. With a 4-core CPU running 200 processes, each process gets about 2% of the CPU. It works because most processes are idle most of the time (waiting for you to type, waiting for network data, etc.).

- **Threads:** A thread is a sub-task within a process. Your browser is one process, but it has many threads: one rendering the page, one handling your mouse clicks, one downloading images, one playing video. Threads within a process share memory — which is efficient but risky (one thread can corrupt another's data, causing crashes).

- **Virtual memory:** The OS creates the illusion that each process has the entire computer's memory to itself. If programs need more RAM than physically exists, the OS silently swaps data to disk. This is why your computer gets *really* slow when RAM is full — it's constantly moving data between RAM and disk (the desk and filing cabinet analogy again).

- Read: The Wikipedia article on "Process (computing)" is genuinely good. For depth: *Operating Systems: Three Easy Pieces* (free online at pages.cs.wisc.edu/~remzi/OSTEP/).

### Terminal Experiments

```bash
# See all running processes — your OS is juggling all of these
ps aux | wc -l    # probably 200-400 processes

# See the process tree — which processes launched which
pstree 2>/dev/null || ps -eo pid,ppid,comm | head -30

# Watch resource usage live (press q to quit)
top -l 1 -n 10 2>/dev/null | head -30 || top -bn1 | head -30

# Create a new process yourself
python3 -c "
import os
print(f'I am process {os.getpid()}')
print(f'My parent process is {os.getppid()}')
# When you run this, Python is a process, launched by your shell (another process)
"

# See what files a process has open (pick a PID from ps output)
# Replace <PID> with an actual number from 'ps aux'
# lsof -p <PID> | head -20

# See virtual memory stats
vm_stat 2>/dev/null | head -10 || vmstat 2>/dev/null | head -5
```

---

## Week 4: Networking, Servers, APIs, and Modern Tooling

### Core Idea
Modern software is rarely one program on one computer. It's many programs on many computers, talking to each other over the network using standardized formats. Understanding APIs (Application Programming Interfaces) is understanding how all these pieces fit together — it's the integration layer of the software world.

### Why It Matters
When someone says "we'll connect our accounting software to the bank's API" or "the dashboard pulls data from a REST API" — this is what they mean. An API is just a structured way for programs to request data from each other. It's like a standardized form: fill in these fields, submit it, get a predictable response.

### What to Read / Think About

- **TCP/IP:** The rules for how computers talk over the internet. TCP guarantees that all packets arrive and in order (like certified mail). IP handles addressing (like zip codes). Together, they're the postal system of the internet.

- **HTTP verbs:** Web APIs use a small set of actions:
  - `GET` — "Give me this data" (reading a report)
  - `POST` — "Here's new data to store" (submitting an invoice)
  - `PUT` — "Replace this data" (updating a record)
  - `DELETE` — "Remove this data" (voiding an entry)
  
  This maps beautifully to CRUD in databases: Create, Read, Update, Delete.

- **JSON:** The universal format for data exchange between programs. It looks like this:
  ```json
  {
    "invoice_number": "INV-2024-001",
    "amount": 5000.00,
    "paid": false
  }
  ```
  If you can read that, you can read JSON. It's intentionally simple.

- **Databases:** Where servers store data permanently. A database is essentially a very sophisticated spreadsheet: tables with rows and columns, but with the ability to efficiently search, filter, and relate millions of rows. SQL (Structured Query Language) is how you query them.

- Read: *HTTP: The Definitive Guide* chapters 1–3 (O'Reilly). Or just read the MDN Web Docs article on HTTP.

### Terminal Experiments

```bash
# Hit a real public API and get data back
curl -s "https://api.github.com/users/torvalds" | python3 -m json.tool | head -20
# That just asked GitHub's server "tell me about user torvalds"
# and got back structured JSON data

# See HTTP headers — the metadata of every web request
curl -s -D - "https://httpbin.org/get" -o /dev/null | head -15

# See what ports are open on your machine (services listening for connections)
lsof -i -P -n 2>/dev/null | grep LISTEN | head -10

# Make a POST request (sending data TO a server)
curl -s -X POST "https://httpbin.org/post" \
  -H "Content-Type: application/json" \
  -d '{"company": "NHC Capital", "type": "test"}' | python3 -m json.tool | head -15

# DNS lookup — translate a name to an IP address
dig +short google.com

# See your own network configuration
ifconfig 2>/dev/null | grep "inet " | grep -v 127.0.0.1 || ip addr show | grep "inet " | grep -v 127.0.0.1
```

---

## What's Next After 30 Days

If you've done even half of this, you now understand more about how computers work than most people who use them 8 hours a day. Here are paths forward depending on your interest:

**If you want to automate accounting tasks:** Learn Python properly. Start with *Automate the Boring Stuff with Python* (free online). Focus on: reading CSVs/Excel, calling APIs, generating reports.

**If you want to understand your company's tech stack:** Ask your developers to walk you through the architecture. You now have the vocabulary and mental models to actually understand the answer.

**If you want to go deeper on systems:** Work through *Computer Systems: A Programmer's Perspective* (CS:APP). It's a college textbook but readable. It goes from bits to networks in one coherent arc.

**If you're curious about databases and SQL:** Try *Select Star SQL* (selectstarsql.com) — an interactive tutorial that teaches SQL through real data. Since you think in spreadsheets, SQL will feel natural.

---

## Turning This Into a Local Site

This Markdown file can be converted into a clean, browsable website with a single command:

```bash
# Option 1: Python's built-in Markdown → HTML (no installs)
python3 -c "
import markdown, pathlib
md = pathlib.Path('docs/how-computers-work.md').read_text()
html = f'<html><head><meta charset=\"utf-8\"><style>body{{max-width:800px;margin:40px auto;padding:0 20px;font-family:system-ui;line-height:1.6}}code{{background:#f4f4f4;padding:2px 6px;border-radius:3px}}pre{{background:#f4f4f4;padding:16px;border-radius:8px;overflow-x:auto}}</style></head><body>{markdown.markdown(md, extensions=[\"tables\",\"fenced_code\"])}</body></html>'
pathlib.Path('/tmp/how-computers-work.html').write_text(html)
print('Open /tmp/how-computers-work.html in your browser')
"

# Option 2: Use a static site generator like MkDocs for a polished result
# pip install mkdocs-material && mkdocs new . && mkdocs serve
```

For a team-internal reference, the Markdown file itself works great in GitLab/GitHub — they render it natively with full formatting.
