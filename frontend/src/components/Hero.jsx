import React from 'react';
import { 
  ArrowRight, 
  Sparkles, 
  Layers, 
  GitFork, 
  FileCode2, 
  Database, 
  Cpu, 
  Activity,
  Code
} from 'lucide-react';

export const Hero = () => {
  return (
    <section className="relative pt-12 pb-24 md:pt-20 md:pb-32 overflow-hidden">
      {/* Background radial gradient glow */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[350px] bg-gradient-to-tr from-indigo-500/20 via-violet-500/15 to-transparent blur-[120px] pointer-events-none -z-10" />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-8 items-center">
          
          {/* Left Column: Headline & CTA */}
          <div className="lg:col-span-6 space-y-6 text-center lg:text-left">
            
            {/* Pill Badge */}
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 border border-indigo-200/80 dark:border-indigo-800/80 shadow-sm">
              <Sparkles className="w-3.5 h-3.5 animate-pulse" />
              <span>Next-Gen Code Intelligence Platform</span>
            </div>

            {/* Main Headline */}
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-slate-900 dark:text-white leading-[1.12]">
              Understand Your Codebase.{' '}
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 via-violet-600 to-pink-500 dark:from-indigo-400 dark:via-violet-400 dark:to-pink-400">
                Beyond the Code.
              </span>
            </h1>

            {/* Supporting Paragraph */}
            <p className="text-base sm:text-lg text-slate-600 dark:text-slate-400 leading-relaxed max-w-2xl mx-auto lg:mx-0">
              Cypher transforms your repositories into intelligent knowledge graphs, helping developers explore code relationships, understand execution flows and investigate dependencies using AI.
            </p>

            {/* CTA Buttons */}
            <div className="pt-2 flex flex-col sm:flex-row items-center justify-center lg:justify-start gap-4">
              <a
                href="#how-it-works"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl font-semibold text-white bg-indigo-600 hover:bg-indigo-500 active:scale-95 shadow-lg shadow-indigo-600/25 transition-all text-sm"
              >
                Explore Cypher
                <ArrowRight className="w-4 h-4" />
              </a>

              <a
                href="#features"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl font-semibold text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white bg-slate-100 hover:bg-slate-200 dark:bg-white/5 dark:hover:bg-white/10 border border-slate-200 dark:border-white/10 active:scale-95 transition-all text-sm"
              >
                Explore Features
              </a>
            </div>

            {/* Trust highlights */}
            <div className="pt-4 flex items-center justify-center lg:justify-start gap-6 text-xs text-slate-500 dark:text-slate-400 font-mono">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping"></span>
                <span>AST Graph Engine</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-indigo-500"></span>
                <span>Chroma Vector RRF</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-violet-500"></span>
                <span>0% Hallucination Grounding</span>
              </div>
            </div>

          </div>

          {/* Right Column: Code Intelligence & Knowledge Graph Visualization */}
          <div className="lg:col-span-6 relative">
            <div className="relative mx-auto max-w-lg lg:max-w-none">
              
              {/* Outer Glow Canvas */}
              <div className="relative rounded-2xl bg-gradient-to-b from-slate-900 to-[#070b14] border border-slate-800 p-5 shadow-2xl shadow-indigo-950/40 overflow-hidden">
                
                {/* Header bar */}
                <div className="flex items-center justify-between pb-4 border-b border-white/10 mb-4">
                  <div className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full bg-rose-500/80"></div>
                    <div className="w-3 h-3 rounded-full bg-amber-500/80"></div>
                    <div className="w-3 h-3 rounded-full bg-emerald-500/80"></div>
                    <span className="ml-2 text-xs font-mono text-slate-400">knowledge_graph.cypher</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs font-mono text-indigo-400 bg-indigo-950/60 px-2 py-0.5 rounded border border-indigo-800/50">
                    <Activity className="w-3 h-3 animate-spin" />
                    <span>Live Graph Traversal</span>
                  </div>
                </div>

                {/* Simulated Graph Canvas */}
                <div className="relative h-80 sm:h-96 w-full rounded-xl bg-slate-950/80 border border-white/5 overflow-hidden flex items-center justify-center">
                  
                  {/* Subtle Grid Background */}
                  <div className="absolute inset-0 bg-grid-pattern opacity-40"></div>

                  {/* SVG Connection Lines */}
                  <svg className="absolute inset-0 w-full h-full pointer-events-none">
                    <defs>
                      <linearGradient id="edgeGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stopColor="#6366f1" stopOpacity="0.8" />
                        <stop offset="100%" stopColor="#ec4899" stopOpacity="0.8" />
                      </linearGradient>
                    </defs>

                    {/* Edge 1: Module to Class */}
                    <line x1="22%" y1="30%" x2="50%" y2="22%" stroke="url(#edgeGradient)" strokeWidth="1.5" strokeDasharray="3 3" />
                    
                    {/* Edge 2: Class to Method */}
                    <line x1="50%" y1="22%" x2="78%" y2="45%" stroke="#818cf8" strokeWidth="1.5" />
                    
                    {/* Edge 3: Method to Function */}
                    <line x1="78%" y1="45%" x2="52%" y2="75%" stroke="url(#edgeGradient)" strokeWidth="2" />
                    
                    {/* Edge 4: Function to DB Model */}
                    <line x1="52%" y1="75%" x2="22%" y2="68%" stroke="#38bdf8" strokeWidth="1.5" strokeDasharray="4 2" />

                    {/* Edge 5: Central loop */}
                    <line x1="50%" y1="22%" x2="52%" y2="75%" stroke="#a855f7" strokeWidth="1" strokeDasharray="2 2" />
                  </svg>

                  {/* Node 1: Module Node (Top Left) */}
                  <div className="absolute top-[20%] left-[8%] animate-float" style={{ animationDelay: '0s' }}>
                    <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900/90 border border-cyan-500/50 shadow-lg shadow-cyan-500/10 text-cyan-400 text-xs font-mono">
                      <FileCode2 className="w-3.5 h-3.5" />
                      <span>todos/views.py</span>
                    </div>
                  </div>

                  {/* Node 2: Class Node (Top Center) */}
                  <div className="absolute top-[12%] left-[40%] animate-float" style={{ animationDelay: '1.2s' }}>
                    <div className="flex flex-col items-start px-3 py-2 rounded-lg bg-indigo-950/90 border border-indigo-500/70 shadow-lg shadow-indigo-500/20 text-xs font-mono">
                      <div className="flex items-center gap-1.5 text-indigo-300 font-semibold">
                        <Cpu className="w-3.5 h-3.5" />
                        <span>class TodoViewSet</span>
                      </div>
                      <span className="text-[10px] text-indigo-400/80">3 methods • 12 refs</span>
                    </div>
                  </div>

                  {/* Node 3: Function / Method (Right) */}
                  <div className="absolute top-[40%] right-[6%] animate-float" style={{ animationDelay: '2.4s' }}>
                    <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-pink-950/80 border border-pink-500/50 shadow-lg shadow-pink-500/20 text-pink-300 text-xs font-mono">
                      <GitFork className="w-3.5 h-3.5" />
                      <span>def toggle_todo()</span>
                    </div>
                  </div>

                  {/* Node 4: Database Model (Bottom Center) */}
                  <div className="absolute bottom-[18%] left-[42%] animate-float" style={{ animationDelay: '0.8s' }}>
                    <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-950/90 border border-emerald-500/60 shadow-lg shadow-emerald-500/20 text-xs font-mono">
                      <Database className="w-3.5 h-3.5 text-emerald-400" />
                      <div>
                        <div className="text-emerald-300 font-bold">Todo.is_done</div>
                        <div className="text-[10px] text-emerald-400/70">:MODIFIES relationship</div>
                      </div>
                    </div>
                  </div>

                  {/* Floating AST Slice Preview (Bottom Left) */}
                  <div className="absolute bottom-[22%] left-[6%] max-w-[190px] p-2.5 rounded-lg bg-slate-900/95 border border-slate-700/80 shadow-xl backdrop-blur-md hidden sm:block">
                    <div className="text-[10px] font-mono text-slate-400 mb-1 flex items-center justify-between">
                      <span>Line 42-45</span>
                      <span className="text-emerald-400">AST Match</span>
                    </div>
                    <pre className="text-[11px] font-mono text-slate-300 leading-tight">
                      <code>{`todo.is_done = not done\ntodo.save()`}</code>
                    </pre>
                  </div>

                  {/* Center Node: Cypher Hybrid Hub */}
                  <div className="relative z-10 p-3 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-600 text-white shadow-xl shadow-indigo-500/40 ring-4 ring-indigo-500/20 animate-pulse-subtle">
                    <Layers className="w-6 h-6" />
                  </div>

                </div>

                {/* Footer status bar in card */}
                <div className="pt-3 flex items-center justify-between text-xs text-slate-400 font-mono">
                  <span>Knowledge Graph: 142 Nodes • 280 Edges</span>
                  <span className="text-emerald-400 font-semibold">Graph-Vector Sync: OK</span>
                </div>

              </div>

            </div>
          </div>

        </div>
      </div>
    </section>
  );
};
