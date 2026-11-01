# FRONTEND_PART_1: Cypher UI Specification & Architecture Blueprint

> **Document Status**: Draft / Approved for Part 1 Frontend Implementation  
> **Target Version**: Cypher Web UI v1.0  
> **Tech Stack**: React 18+, Vite, JavaScript (ESNext), React Router v6, Tailwind CSS, Lucide React  
> **Scope**: Frontend-only UI components, layouts, local states, client-side routing, and mock interaction paradigms. Backend APIs and live Neo4j queries are strictly decoupled and documented for future integration.

---

## 1. Project Overview

**Cypher** is a code intelligence platform and code knowledge graph system designed to help developers inspect, explore, and understand complex software codebases without cognitive overload. 

Rather than forcing developers to read thousands of disconnected files or browse clumsy documentation trees, Cypher statically analyzes repositories, maps their structural relationships (e.g., function calls, class inheritance, file imports, route mappings for Django, FastAPI, and Flask), loads them into a knowledge graph, and provides an intuitive, conversational interface.

This document serves as the authoritative, engineering-grade specification for **Frontend Part 1**. It details every view, component hierarchy, design token, state machine, and mock data interface needed to construct the complete client-side application before backend integration.

---

## 2. Product Vision

The guiding vision for Cypher's frontend is **effortless code intelligence through conversational simplicity**.

Traditional software engineering tools suffer from dashboard fatigue: cluttered menus, overwhelming tables, complex navigation breadcrumbs, and dense admin panels. In contrast, Cypher draws UX inspiration from modern conversational tools like ChatGPT and Claude:
- **Clean and Minimal**: The interface puts the user's intent front and center.
- **Chat-First Workflow**: Exploring a codebase feels like discussing a project with a senior software architect who has memorized every line of code.
- **Immediate Contextual Entry**: Users can drop a ZIP archive or paste a Git repository URL directly into a welcoming prompt composer.
- **Developer-Centric Aesthetics**: Monospace touches for identifiers, keyboard accessibility, high-contrast dark/light modes, subtle borders, and zero gratuitous marketing animations.
- **Seamless Graph Discovery**: Visualizing code relationships is one click away via an interactive graph canvas without feeling detached from the chat workspace.

---

## 3. UI/UX Design Principles

Cypher's interface adheres to six core design principles:

1. **Content Over Chrome**
   Chromium borders, toolbars, and extraneous buttons are stripped away. Navigation is tucked into a collapsible sidebar, reserving >85% of viewport real estate for the conversation stream and graph canvas.

2. **Keyboard-First Ergonomics**
   Key actions support standard developer shortcuts:
   - `Ctrl/Cmd + K`: Open search / command palette.
   - `Ctrl/Cmd + Shift + O`: Start New Chat / Reset Context.
   - `Ctrl/Cmd + B`: Toggle Sidebar collapse/expand.
   - `Enter` (without Shift): Submit prompt in composer.
   - `Shift + Enter`: Multi-line prompt line break.
   - `Escape`: Close modals, dropdowns, and flyout sidebars.

3. **Subtle Depth & High-Contrast Typography**
   Avoid loud neon gradients and glassmorphism. Depth is achieved through restrained border contrast (`border-slate-200` in light mode, `border-neutral-800` in dark mode) and subtle elevation shadows (`shadow-sm`, `shadow-md`).

4. **Information Density with Breathing Room**
   Code snippets, terminal outputs, and symbol references must be readable. Code blocks use clean monospace fonts (e.g., *JetBrains Mono*, *Fira Code*, or *SF Mono*) with adequate padding and copy-to-clipboard actions.

5. **Clarity of Operational State**
   Every asynchronous operation (analyzing code, parsing AST, building graph, streaming AI response) must present dedicated, distinct visual states: Idle, Loading/Scanning, Progress Tracker, Success, and Informative Error.

6. **Accessibility & Responsive Grace**
   Touch targets on mobile are >=44px. Color contrasts comply with WCAG AA standards. The interface collapses into a single-column layout with a slide-over drawer on viewports < 768px.

---

## 4. Main Application Layout

The core layout consists of a two-panel flex shell spanning 100vw and 100vh with zero window-level overflow scrolling:

```
+------------------------------------------------------------------------------------+
|  [Sidebar Toggle Button (Mobile / Floating)]                                       |
| +---------------------+ +--------------------------------------------------------+ |
| |  CYPHER SIDEBAR     | |  MAIN CONTENT VIEWPORT                                 | |
| |  (w-64 / w-16 / 0)  | |  (flex-1 flex flex-col h-full overflow-hidden)         | |
| |                     | |                                                        | |
| |  [Logo + Brand]     | |  Top Header Bar (Breadcrumb / Active Repo / Actions)   | |
| |  [+ New Chat]       | |--------------------------------------------------------| |
| |                     | |                                                        | |
| |  Chat History List  | |  Scrollable Workspace:                                 | |
| |  - "Django User..." | |  - Welcome Hero (Empty State) OR Chat Message Stream   | |
| |  - "FastAPI Auth..."| |                                                        | |
| |                     | |--------------------------------------------------------| |
| |  -----------------  | |  Bottom Anchored Composer Container:                   | |
| |  [Graph Explorer]   | |  +--------------------------------------------------+  | |
| |  [Theme Toggle]     | |  | [ZIP Upload] [GitHub URL]                        |  | |
| |  [User Profile]     | |  | Input prompt: "Ask anything about codebase..." |  | |
| |                     | |  +--------------------------------------------------+  | |
| +---------------------+ +--------------------------------------------------------+ |
+------------------------------------------------------------------------------------+
```

### Layout Breakdown
- **Outer Shell**: `h-screen w-screen flex overflow-hidden bg-white dark:bg-neutral-950 text-neutral-900 dark:text-neutral-100`
- **Left Sidebar**: `fixed md:relative z-40 h-full transition-all duration-300 ease-in-out border-r border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900`
- **Main Viewport**: `flex-1 flex flex-col h-full min-w-0 overflow-hidden relative`
- **Message Area**: `flex-1 overflow-y-auto px-4 md:px-8 py-6 max-w-4xl w-full mx-auto`
- **Input Area**: `sticky bottom-0 w-full px-4 md:px-8 pb-6 pt-2 bg-gradient-to-t from-white via-white dark:from-neutral-950 dark:via-neutral-950 to-transparent`

---

## 5. Sidebar Specification

The sidebar (`Sidebar.jsx`) provides persistence across user interactions while remaining completely unobtrusive.

### 5.1 Sidebar Anatomy
1. **Brand Header**:
   - Monogram SVG icon representing Cypher's graph nodes.
   - Text label: `Cypher` (hidden when collapsed to icon-only rail).
   - Version tag: `v1.0-alpha`.
   - Toggle button with icon `PanelLeftClose` / `PanelLeftOpen`.

2. **Primary Action**:
   - Button: `+ New Chat`
   - Shortcut hint: `⌘O`
   - Styling: Subtle border, hover highlight (`hover:bg-neutral-200 dark:hover:bg-neutral-800`).

3. **Repository Context Banner (When Active)**:
   - Displays currently loaded repository name (e.g., `sample_repo (Django)`).
   - Node count badge (e.g., `74 nodes`).
   - Quick action to jump directly to `/repositories/:id/graph`.

4. **Chat History Section**:
   - Section label: `Recent Chats`.
   - Scrollable list of previous conversations grouped chronologically:
     - *Today*
     - *Yesterday*
     - *Previous 7 Days*
   - Each item includes:
     - Message bubble icon.
     - Truncated conversation title.
     - Hover actions: Rename (`Edit3`) and Delete (`Trash2`).
     - Active indicator line on the leading edge.

5. **Tools & Navigation Section**:
   - `Graph Explorer` link with `Network` / `GitFork` icon.
   - `Documentation` link with `BookOpen` icon.

6. **Footer / User Profile Dock**:
   - User avatar (initials or profile image).
   - User display name and email (truncated).
   - Settings trigger (`Settings` icon).
   - Sign In / Sign Out button based on authentication state.

### 5.2 Sidebar State Machine
- **Expanded (`w-64`)**: Full text, chat history with titles, profile details visible. Default on desktop (`>= 1024px`).
- **Collapsed (`w-16`)**: Desktop compact mode. Shows only icons with floating tooltips on hover.
- **Mobile Closed (`-translate-x-full`)**: Off-canvas drawer. Opens on hamburger tap with background backdrop blur (`bg-black/50`).

---

## 6. Page-by-Page Specifications

### Page 1: Main Chat / Home Page (`/` and `/chat/:chatId`)

#### Purpose
The primary interactive interface where developers upload repositories, inspect code structure, review analysis summaries, and chat with their codebase.

#### Layout
- Fixed Top Header: Displays conversation title or "New Code Conversation", active repository pill, and layout controls.
- Central Scroll Area: Switches between **Zero-State (Hero)** and **Conversation Stream**.
- Sticky Bottom Composer: Houses the multi-mode repository intake and prompt box.

#### Visual States
1. **Empty / Welcome State (No repository loaded)**:
   - Centered Cypher logo with subtle glow.
   - Heading: *"Understand your codebase in seconds."*
   - Subtitle: *"Upload a repository ZIP or connect via GitHub URL to map dependencies, trace route hierarchies, and inspect function call chains."*
   - **Repository Intake Card** (embedded directly above prompt bar):
     - Segmented Tabs: `[ ZIP Upload ]` and `[ GitHub URL ]`
     - Tab A (ZIP): Drag-and-drop file target with dashed border, icon, *"Drag & drop .zip here, or browse"*, and max size label (*Max 50MB*).
     - Tab B (GitHub): Input box with GitHub icon, placeholder `https://github.com/owner/repository`, branch selector, and `Connect` button.
   - Suggestion Chips below input:
     - *"Where is the authentication view defined?"*
     - *"List all API routes and their HTTP methods"*
     - *"Trace the call chain for user creation"*
     - *"Show database models and their relationships"*

2. **Analysis Progress State**:
   - When a repository is uploaded/connected, a progress card appears in the chat stream:
     - Step 1: `Extracting repository files...` (Completed checkmark)
     - Step 2: `AST Parsing & Symbol Indexing...` (Completed checkmark)
     - Step 3: `Resolving cross-file imports & call chains...` (Spinner)
     - Step 4: `Detecting framework routes (Django/FastAPI/Flask)...` (Pending)
     - Step 5: `Validating Knowledge Graph payload...` (Pending)
   - Progress bar (0% to 100%).

3. **Active Conversation State**:
   - Alternating message cards:
     - **User Prompt**: Right-aligned or standard card with user avatar, timestamp, and query text.
     - **Cypher Assistant Response**: Left-aligned with Cypher brand icon. Supports:
       - Markdown formatted text.
       - Syntax-highlighted code blocks with language tag and "Copy Code" button.
       - Interactive Symbol Links (e.g., clicking on `[users.services.list_users]` highlights the symbol).
       - Context Badges showing source files referenced (e.g., `users/views.py:15`).
       - Quick Link: *"View in Interactive Graph"* button.

4. **Composer Component (`ChatComposer.jsx`)**:
   - Multi-line autosizing textarea (`max-h-48`).
   - Action buttons inside composer:
     - `Attach Repo / File` button (`Paperclip`).
     - `Repo Indicator Tag` (e.g., `sample_repo.zip ✕`) when attached.
     - `Voice / Dictation` placeholder (disabled/hidden).
     - `Send Button` (`ArrowUp` or `Send`) with active state when text/file is present.

---

### Page 2: Repository Visualization Page (`/repositories/:repositoryId/graph`)

#### Purpose
An interactive, canvas-based visual representation of the analyzed codebase knowledge graph (Files, Modules, Classes, Functions, Routes, and their relationships).

#### Layout
- **Full Viewport Canvas**: Powered by a visual graph surface (e.g., SVG/HTML5 Canvas via React Flow or VisX structure).
- **Floating Top Bar**:
  - Back to Chat button (`ArrowLeft`).
  - Repository title and badge: `users_service • 74 nodes, 96 relationships`.
  - Filter by Entity Type dropdowns: `[✓] Modules  [✓] Classes  [✓] Functions  [✓] Routes`.
  - Filter by Relationship dropdowns: `[✓] CALLS  [✓] IMPORTS  [✓] ROUTES_TO  [✓] INHERITS`.
  - Search node input (`Search symbols...`).
- **Floating Canvas Controls (Bottom Right)**:
  - Zoom In (`+`), Zoom Out (`-`), Fit View (`Maximize2`), Reset (`RotateCcw`).
  - Layout switch: `Hierarchical (DAG)` vs `Force-Directed (Organic)`.
- **Node Details Slide-Out Drawer (Right Side, w-80)**:
  - Opens when a user clicks any node on the graph.
  - Displays:
    - Entity Kind Badge (`Function`, `Class`, `Route`, `Module`).
    - Qualified Name (e.g., `users.services.create_user_with_profile`).
    - File Path & Line Numbers (e.g., `users/services.py:32-48`).
    - Docstring preview block.
    - Incoming Relationships (e.g., `Called by users.views.user_create`).
    - Outgoing Relationships (e.g., `Calls users.repository.create_user`).
    - Button: *"Ask in Chat about this symbol"*.

#### Part 1 Implementation Scope
- Static mock canvas displaying simulated nodes and edges representing `sample_repo` (Django).
- Functional zoom/pan controls and filter buttons (toggling mock visibility).
- Node click triggers the slide-out inspector with hardcoded representative metadata.
- **Zero live Neo4j WebSocket or REST graph polling** in Part 1.

---

### Page 3: Login Page (`/login`)

#### Purpose
Authentication gateway for returning users.

#### Layout
- Clean, centered card (`max-w-md w-full`) on a subtle background.
- Cypher icon and title: *"Welcome back to Cypher"*.
- Subtitle: *"Sign in to access your analyzed codebases and chat history."*
- Form Elements:
  - Email field (`type="email"`, placeholder `developer@company.com`).
  - Password field (`type="password"`, with show/hide toggle).
  - Row: *"Remember this device"* checkbox + *"Forgot password?"* link.
  - Primary Submit Button: *"Sign In"*.
  - Divider: *"OR CONTINUE WITH"*.
  - Social Sign-in Button: `Continue with GitHub` (prominent for developer audience).
- Footer: *"Don't have an account? Sign up"*.

---

### Page 4: Register Page (`/register`)

#### Purpose
Onboarding interface for new developers.

#### Layout
- Centered card matching the Login layout for visual continuity.
- Title: *"Create your Cypher account"*.
- Subtitle: *"Start exploring and visualizing your repositories in minutes."*
- Form Elements:
  - Full Name field.
  - Work Email field.
  - Password field with client-side password strength meter (Weak / Medium / Strong).
  - Confirm Password field.
  - Checkbox: *"I agree to the Terms of Service and Privacy Policy"*.
  - Primary Submit Button: *"Create Account"*.
  - Social Sign-in Button: `Sign up with GitHub`.
- Footer: *"Already have an account? Sign in"*.

---

### Page 5: User Profile & Settings Page (`/settings`)

#### Purpose
Minimal developer configuration panel. Strictly eliminates vanity metrics, complex billing, or enterprise bloat.

#### Layout
- Centered container (`max-w-2xl mx-auto py-10 px-4`).
- Section 1: **Profile Information**
  - Avatar placeholder with "Change Avatar" button.
  - Name (Input field).
  - Email address (Read-only badge: `Verified`).
- Section 2: **Preferences**
  - Theme Selector: Radio group or segmented pill (`Light`, `Dark`, `System Default`).
  - Code Block Font Preference: `Fira Code`, `JetBrains Mono`, `System Monospace`.
  - Default Framework Filter: `Auto-Detect`, `Django`, `FastAPI`, `Flask`.
- Section 3: **Storage & Privacy**
  - Button: `Clear Local Chat History` (with confirmation alert).
  - Button: `Delete Account & Cached Repositories` (`text-red-600`).
- Top-right / Bottom action: `Save Changes` button.

---

## 7. Reusable Components

To ensure rapid assembly and zero code duplication, the frontend architecture defines the following component catalog:

### 7.1 Layout & Shell Components
| Component Name | File Path | Props | Purpose |
|---|---|---|---|
| `AppShell` | `src/components/layout/AppShell.jsx` | `children` | Top-level responsive flex container, sidebar drawer wrapper. |
| `Sidebar` | `src/components/layout/Sidebar.jsx` | `isCollapsed, onToggle, currentChatId` | Collapsible navigation, chat history listing, user dock. |
| `Header` | `src/components/layout/Header.jsx` | `title, activeRepo, onOpenSidebar` | Minimal top bar with mobile hamburger and repo status pill. |

### 7.2 Chat Components
| Component Name | File Path | Props | Purpose |
|---|---|---|---|
| `ChatContainer` | `src/components/chat/ChatContainer.jsx` | `messages, isLoading` | Scrollable message stream with autoscroll to bottom. |
| `ChatMessage` | `src/components/chat/ChatMessage.jsx` | `message: { sender, text, timestamp, symbols, codeSnippets }` | Individual user or assistant speech bubble with syntax highlighting. |
| `ChatComposer` | `src/components/chat/ChatComposer.jsx` | `onSendMessage, onUploadZip, onConnectGit, disabled` | Textarea, file attach trigger, submit button, shortcut handlers. |
| `EmptyHero` | `src/components/chat/EmptyHero.jsx` | `onSelectSuggestion` | Welcome title, prompt suggestions, and embedded repo intake. |
| `AnalysisProgress` | `src/components/chat/AnalysisProgress.jsx` | `steps: [], currentStep, percent` | Step-by-step progress checklist for repo scanning. |

### 7.3 Repository Intake Components
| Component Name | File Path | Props | Purpose |
|---|---|---|---|
| `RepoIntakeCard` | `src/components/repo/RepoIntakeCard.jsx` | `onZipSelect, onGitSubmit, isProcessing` | Tabbed selector for ZIP upload vs GitHub clone URL. |
| `ZipDropzone` | `src/components/repo/ZipDropzone.jsx` | `onFileAccepted, maxSizeBytes` | Drag-and-drop zone with file validation (`.zip` only). |
| `GitUrlForm` | `src/components/repo/GitUrlForm.jsx` | `onSubmitUrl, branches: []` | Input field for GitHub HTTPS URL + branch option. |

### 7.4 Graph Visualization Components
| Component Name | File Path | Props | Purpose |
|---|---|---|---|
| `GraphCanvas` | `src/components/graph/GraphCanvas.jsx` | `nodes, edges, onNodeClick, selectedNodeId` | Interactive pan/zoom surface rendering nodes and relationships. |
| `GraphControls` | `src/components/graph/GraphControls.jsx` | `onZoomIn, onZoomOut, onFitView, onReset` | Floating action pill for canvas manipulation. |
| `GraphFilters` | `src/components/graph/GraphFilters.jsx` | `activeFilters, onToggleFilter` | Filter pills for Entity Kinds and Relationship Types. |
| `NodeDetailsDrawer` | `src/components/graph/NodeDetailsDrawer.jsx` | `node, onClose, onAskAboutNode` | Slide-out panel inspecting qualified names, docstrings, calls. |

### 7.5 Common / Atom UI Components (`src/components/ui/`)
- `Button.jsx`: Variants (`primary`, `secondary`, `outline`, `ghost`, `danger`), sizes (`sm`, `md`, `lg`), loading spinner.
- `Input.jsx`: Standard text input with label, error message, and prefix/suffix icons.
- `Modal.jsx`: Accessible dialog with backdrop blur, focus trap, and escape key listener.
- `Badge.jsx`: Color-coded entity badges (`Function` = blue, `Class` = purple, `Route` = emerald, `Module` = amber).
- `Tooltip.jsx`: Micro-copy tooltip on hover for collapsed sidebar and icon buttons.
- `Dropdown.jsx`: Accessible menu for chat item actions (Rename, Delete).

---

## 8. React Folder Structure

The frontend application follows an industry-standard, feature-grouped directory structure under `src/`:

```
frontend/
├── index.html
├── package.json
├── vite.config.js
├── tailwind.config.js
├── postcss.config.js
├── public/
│   ├── favicon.svg
│   └── cypher-logo.svg
└── src/
    ├── main.jsx                     # Application entrypoint
    ├── App.jsx                      # Root router and global providers
    ├── index.css                    # Tailwind directives and CSS variables
    │
    ├── assets/                      # Static icons, illustrations
    │
    ├── components/                  # Reusable presentation components
    │   ├── layout/
    │   │   ├── AppShell.jsx
    │   │   ├── Sidebar.jsx
    │   │   └── Header.jsx
    │   ├── chat/
    │   │   ├── ChatContainer.jsx
    │   │   ├── ChatMessage.jsx
    │   │   ├── ChatComposer.jsx
    │   │   ├── EmptyHero.jsx
    │   │   └── AnalysisProgress.jsx
    │   ├── repo/
    │   │   ├── RepoIntakeCard.jsx
    │   │   ├── ZipDropzone.jsx
    │   │   └── GitUrlForm.jsx
    │   ├── graph/
    │   │   ├── GraphCanvas.jsx
    │   │   ├── GraphControls.jsx
    │   │   ├── GraphFilters.jsx
    │   │   └── NodeDetailsDrawer.jsx
    │   └── ui/
    │       ├── Button.jsx
    │       ├── Input.jsx
    │       ├── Badge.jsx
    │       ├── Modal.jsx
    │       ├── Tooltip.jsx
    │       └── Dropdown.jsx
    │
    ├── pages/                       # Route view components
    │   ├── ChatPage.jsx             # Main conversational workspace (Home)
    │   ├── GraphPage.jsx            # Dedicated repository graph explorer
    │   ├── LoginPage.jsx            # Authentication: Sign In
    │   ├── RegisterPage.jsx         # Authentication: Sign Up
    │   ├── SettingsPage.jsx         # Minimal user profile and preferences
    │   └── NotFoundPage.jsx         # 404 handler
    │
    ├── context/                     # Client-side React context providers
    │   ├── ThemeContext.jsx         # Dark / Light theme persistence
    │   ├── ChatContext.jsx          # Mock conversation state in Part 1
    │   └── RepositoryContext.jsx    # Selected repository state & metadata
    │
    ├── hooks/                       # Custom utility hooks
    │   ├── useTheme.js              # Theme accessor
    │   ├── useMediaQuery.js         # Viewport breakpoint detection
    │   └── useLocalStorage.js       # Typed localStorage synchronization
    │
    ├── data/                        # Static mock data for Part 1 development
    │   ├── mockChats.js             # Initial sidebar conversation history
    │   ├── mockMessages.js          # Pre-populated conversation for ChatPage
    │   └── mockGraphData.js         # Realistic node/edge JSON for GraphPage
    │
    └── utils/                       # Pure utility helpers
        ├── cn.js                    # clsx + twMerge utility for class names
        ├── formatters.js            # Timestamp and file size formatters
        └── constants.js             # Application-wide constants and routes
```

---

## 9. Routing Specification

Routing is powered by `react-router-dom` v6 with client-side layout nesting.

| Route Path | View Component | Access Level | Description | Part 1 Status |
|---|---|---|---|---|
| `/` | `ChatPage.jsx` | Public / Mocked Auth | Default home view. Shows Empty Hero + Repo Intake if no chat is active. | **Frontend-only** (Fully operational with local mock state) |
| `/chat/:chatId` | `ChatPage.jsx` | Public / Mocked Auth | Loads specific conversation thread by ID from local mock store. | **Frontend-only** (Pre-populated sample thread) |
| `/repositories/:repositoryId/graph` | `GraphPage.jsx` | Public / Mocked Auth | Visualizes code knowledge graph of the specified repository. | **Frontend-only** (Interactive mock graph canvas) |
| `/login` | `LoginPage.jsx` | Public | Sign In form. Submitting routes back to `/` with mock active user. | **Frontend-only** (Form validation only, no real token) |
| `/register` | `RegisterPage.jsx` | Public | Registration form with password confirmation. | **Frontend-only** (Form validation only) |
| `/settings` | `SettingsPage.jsx` | Public / Mocked Auth | Profile preferences, theme selector, clear history. | **Frontend-only** (Stores preferences in `localStorage`) |
| `*` | `NotFoundPage.jsx` | Public | Friendly 404 page with "Return to Chat" button. | **Frontend-only** |

---

## 10. Frontend-Only Features (Part 1 Implementation Scope)

These features **will be completely built and functional** in Part 1 using pure client-side React code and mock data:

1. **Collapsible ChatGPT-Style Sidebar**:
   - Smooth expand/collapse animation (`w-64` to `w-16` on desktop, slide-over drawer on mobile).
   - Chat history grouping (Today, Yesterday, Previous 7 Days).
   - Local state renaming and deleting of chat history items.

2. **Welcome Screen & Conversation Shell**:
   - Minimalist hero banner.
   - Clickable suggestion chips that populate the composer input.
   - Complete message bubble rendering with markdown typography and syntax highlighting styling.

3. **Repository Intake UI**:
   - Tab switching between ZIP Upload and GitHub URL.
   - Drag-and-drop visual dropzone with drag-over state changes.
   - Client-side validation (e.g., verifying file extension is `.zip`, checking file size limit < 50MB, validating GitHub URL format).
   - Mock scan progress simulator (animating steps from 0% to 100% when a mock upload occurs).

4. **Interactive Mock Graph Canvas**:
   - Responsive SVG/HTML5 canvas with interactive pan, zoom, and reset controls.
   - Simulated code entities (File, Module, Class, Function, Route) with distinct badge styling.
   - Clickable nodes that slide open the `NodeDetailsDrawer` showing static symbol details.
   - Filter pills that toggle node visibility locally.

5. **Theme Switching**:
   - Instant toggle between Dark and Light mode.
   - Persists user selection in `localStorage` and syncs with `document.documentElement.classList`.

6. **Authentication Form Layouts**:
   - Polished Login and Registration cards with floating labels, input validation feedback, and show/hide password buttons.

---

## 11. Backend-Dependent Features (Strictly Deferred from Part 1)

These features require live APIs, databases, authentication servers, or Python background workers and **must NOT be implemented in Part 1**:

1. **Real User Authentication**:
   - JWT token issuance, refresh tokens, OAuth2 flows with GitHub, database session storage, password reset email delivery.
2. **Actual ZIP Extraction & AST Analysis**:
   - Uploading a 50MB ZIP to FastAPI backend, disk unzipping, running `ast_parser.py`, and running `engine.py`.
3. **Live GitHub Cloning**:
   - Backend `git clone` execution, branch checkout, and AST scanning on server storage.
4. **Live Neo4j Graph Queries**:
   - Running Cypher queries via `neo4j_client.py` or streaming nodes/edges dynamically over WebSockets/REST.
5. **Real AI / LLM Streaming Responses**:
   - Integrating OpenAI, Anthropic, or Gemini APIs to synthesize answers from graph context.
6. **Cloud Database Chat Persistence**:
   - Saving conversation history to PostgreSQL/MongoDB across separate client devices.

---

## 12. Future API Integration Points

To ensure the Part 1 frontend seamlessly hooks into the FastAPI backend (`cypher/api/routes.py`) in Part 2, the following REST endpoints and payload contracts are formally defined:

### 12.1 Authentication & User Endpoints
- `POST /api/auth/register`: `{ name, email, password }` -> `{ token, user }`
- `POST /api/auth/login`: `{ email, password }` -> `{ token, user }`
- `GET /api/auth/me`: Headers: `Authorization: Bearer <token>` -> `{ id, name, email }`

### 12.2 Repository Analysis Endpoints
- `POST /api/repositories/upload-zip`:
  - Request: `multipart/form-data` with `file: <binary.zip>`
  - Response: `{ repository_id, name, status: "processing", task_id }`
- `POST /api/repositories/connect-git`:
  - Request: `{ url: "https://github.com/...", branch: "main" }`
  - Response: `{ repository_id, name, status: "processing", task_id }`
- `GET /api/repositories/:id/status`:
  - Polling or WebSocket endpoint returning stage: `"parsing" | "indexing" | "resolving" | "graph_building" | "completed"` and `percent: 85`.

### 12.3 Knowledge Graph Endpoints
- `GET /api/repositories/:id/graph`:
  - Returns the graph-ready JSON payload matching `RelationshipBuilder.build()`:
    ```json
    {
      "repository": { "id": "repo_123", "name": "sample_repo" },
      "entities": [
        { "id": "func_1", "kind": "function", "name": "list_users", "qualified_name": "users.services.list_users", "file_path": "users/services.py", "line": 10 }
      ],
      "relationships": [
        { "id": "rel_1", "type": "CALLS", "source_id": "func_1", "target_id": "func_2", "line": 12 }
      ],
      "stats": { "total_entities": 74, "total_relationships": 96 }
    }
    ```

### 12.4 Chat & Code Intelligence Endpoints
- `POST /api/chats`: Create new thread -> `{ chat_id, title }`
- `GET /api/chats`: List threads -> `[{ chat_id, title, updated_at }]`
- `POST /api/chats/:id/messages`:
  - Request: `{ prompt: "Which view handles /users/?" }`
  - Response: Server-Sent Events (SSE) stream yielding token chunks, followed by referenced entity IDs.

---

## 13. Responsive Design Requirements

Cypher must remain fully functional across all standard viewport tiers:

| Viewport Tier | Breakpoint | Sidebar Behavior | Content Area Layout | Composer Layout |
|---|---|---|---|---|
| **Desktop Wide** | `>= 1280px` | Open by default (`w-64`). Toggleable to compact rail (`w-16`). | Max container width `max-w-4xl`, centered. Graph drawer side-by-side (`w-80`). | Floating rounded container with generous padding. |
| **Desktop Standard** | `1024px - 1279px` | Open by default (`w-64`). | Standard conversational stream. Graph drawer overlays right edge. | Full width with padding. |
| **Tablet** | `768px - 1023px` | Collapsed to icon rail (`w-16`) by default. Expands on hover or button tap. | Single column stream. Graph canvas fills screen, drawer overlays full height. | Anchored to bottom. |
| **Mobile** | `< 768px` | Hidden off-canvas. Triggered via header hamburger icon with backdrop overlay. | Full-width stream (`px-3 py-4`). Touch targets scaled to >=44px. | Compact composer, attachment buttons collapse into a secondary menu sheet. |

---

## 14. Dark & Light Theme Requirements

Cypher features a first-class dark mode tailored for software engineers who work in dark IDE environments, while maintaining an equally clean, high-contrast light theme:

### Color Token Palette

| Token Role | Light Mode Value | Dark Mode Value | Tailwind Equivalent |
|---|---|---|---|
| **App Background** | `#FFFFFF` | `#0A0A0A` | `bg-white dark:bg-neutral-950` |
| **Sidebar / Surface Background** | `#F9FAFB` (Neutral 50) | `#141414` (Neutral 900) | `bg-neutral-50 dark:bg-neutral-900` |
| **Card / Modal Surface** | `#FFFFFF` | `#1A1A1A` | `bg-white dark:bg-neutral-900/80` |
| **Primary Text** | `#111827` (Gray 900) | `#F9FAFB` (Neutral 50) | `text-neutral-900 dark:text-neutral-100` |
| **Secondary / Muted Text** | `#4B5563` (Gray 600) | `#9CA3AF` (Neutral 400) | `text-neutral-600 dark:text-neutral-400` |
| **Subtle Borders** | `#E5E7EB` (Gray 200) | `#262626` (Neutral 800) | `border-neutral-200 dark:border-neutral-800` |
| **Accent / Brand Brand Blue** | `#2563EB` (Blue 600) | `#3B82F6` (Blue 500) | `bg-blue-600 dark:bg-blue-500` |
| **Code Block Background** | `#F3F4F6` (Gray 100) | `#0D1117` (GitHub Dark) | `bg-neutral-100 dark:bg-neutral-900` |
| **Success / Route Badge** | `#059669` (Emerald 600) | `#10B981` (Emerald 500) | `text-emerald-600 dark:text-emerald-400` |
| **Warning / Class Badge** | `#D97706` (Amber 600) | `#F59E0B` (Amber 500) | `text-amber-600 dark:text-amber-400` |

### Implementation Rules
- Theme class `dark` is appended directly to `document.documentElement`.
- The system theme is evaluated via `window.matchMedia('(prefers-color-scheme: dark)')` when `theme === 'system'`.
- No inline styles for color management; strictly rely on Tailwind's `dark:` variant.

---

## 15. Part 1 Development Scope

The following checklist represents the exact scope of deliverable work for Part 1:

- [ ] Initialize Vite + React project structure under a designated `frontend/` directory.
- [ ] Install and configure Tailwind CSS, PostCSS, Autoprefixer, `lucide-react`, and `react-router-dom`.
- [ ] Configure typography and CSS variables for smooth light/dark switching.
- [ ] Build reusable UI primitives: `Button`, `Input`, `Badge`, `Modal`, `Tooltip`, `Dropdown`.
- [ ] Build the responsive `AppShell` with the collapsible ChatGPT-style `Sidebar`.
- [ ] Implement `EmptyHero` with prompt suggestion chips and embedded `RepoIntakeCard`.
- [ ] Implement drag-and-drop file dropzone for ZIP uploads (with client-side format & size validation).
- [ ] Implement GitHub URL input form with regex validation.
- [ ] Build animated `AnalysisProgress` component simulating the 5-stage repository analysis.
- [ ] Construct the `ChatMessage` and `ChatComposer` conversation view.
- [ ] Create static `GraphPage` with interactive canvas controls (pan, zoom, fit view, filter pills) and slide-out `NodeDetailsDrawer` using sample Django graph data (`sample_repo`).
- [ ] Build clean, responsive `LoginPage` and `RegisterPage` layouts.
- [ ] Build minimal `SettingsPage` with theme preference toggling and local history reset.
- [ ] Populate mock data files (`mockChats.js`, `mockMessages.js`, `mockGraphData.js`) to provide immediate, realistic visual fidelity.

---

## 16. Features Explicitly Excluded from Part 1

The following capabilities are **explicitly out of scope** for Part 1 and must NOT be added until backend endpoints are ready:

- ❌ Connecting to real Neo4j database or issuing actual Cypher queries.
- ❌ Running real Python subprocesses (`ast_parser.py`, `engine.py`) in the browser or via unconfigured servers.
- ❌ Real user registration, login JWT verification, or password recovery emails.
- ❌ LLM API calls (OpenAI, Gemini, Ollama, etc.) or AI response streaming.
- ❌ Git cloning over the network.
- ❌ Complex payment, team workspace, or enterprise role-based access control (RBAC).

---

## 17. Conclusion & Next Steps

This document provides a complete, unambiguous blueprint for constructing the Cypher frontend. Any frontend engineer can take this specification, initialize the Vite application, build the component hierarchy, and deliver a polished, responsive ChatGPT-like interface that is 100% ready to bind to Cypher's backend APIs.
