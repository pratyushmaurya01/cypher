import React from 'react';
import { 
  Network, 
  ArrowRight, 
  Terminal, 
  Sparkles 
} from 'lucide-react';

export const CtaAndFooter = () => {
  return (
    <>
      {/* Final Call to Action Section */}
      <section id="get-started" className="py-20 md:py-28 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-indigo-500/5 to-indigo-500/10 dark:via-indigo-950/20 dark:to-indigo-950/30 pointer-events-none" />

        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 relative text-center">
          <div className="p-10 md:p-16 rounded-3xl bg-gradient-to-b from-indigo-900 via-indigo-950 to-[#07090e] border border-indigo-500/30 shadow-2xl shadow-indigo-950/60 text-white space-y-6">
            
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/40">
              <Sparkles className="w-3.5 h-3.5" />
              <span>Ready for Autonomous Codebase Intelligence</span>
            </div>

            <h2 className="text-3xl sm:text-5xl font-extrabold tracking-tight">
              Turn your repository into an actionable graph.
            </h2>

            <p className="max-w-2xl mx-auto text-base sm:text-lg text-indigo-200/80 leading-relaxed">
              Upload your Python codebase, trace cross-module execution flows, and run verified impact analyses with Cypher today.
            </p>

            <div className="pt-4 flex flex-col sm:flex-row items-center justify-center gap-4">
              <a
                href="#features"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-7 py-3.5 rounded-xl font-bold text-slate-900 bg-white hover:bg-slate-100 shadow-lg active:scale-95 transition-all text-sm"
              >
                Launch Cypher Dashboard
                <ArrowRight className="w-4 h-4" />
              </a>

              <a
                href="https://github.com"
                target="_blank"
                rel="noopener noreferrer"
                className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-7 py-3.5 rounded-xl font-bold text-white bg-indigo-800/60 hover:bg-indigo-800 border border-indigo-400/30 active:scale-95 transition-all text-sm"
              >
                <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24">
                  <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
                </svg>
                View Source on GitHub
              </a>
            </div>

            <div className="pt-2 text-xs font-mono text-indigo-300/60 flex items-center justify-center gap-2">
              <Terminal className="w-3.5 h-3.5" />
              <span>uvicorn cypher.main:app • Neo4j + ChromaDB Ready</span>
            </div>

          </div>
        </div>
      </section>

      {/* Professional Footer */}
      <footer className="border-t border-slate-200 dark:border-white/10 bg-white dark:bg-[#06080d] py-12 transition-colors">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          
          <div className="grid grid-cols-1 md:grid-cols-4 gap-8 mb-10">
            
            {/* Col 1: Brand */}
            <div className="md:col-span-2 space-y-4">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white">
                  <Network className="w-4 h-4" />
                </div>
                <span className="font-bold text-lg text-slate-900 dark:text-white">Cypher</span>
              </div>
              <p className="text-sm text-slate-600 dark:text-slate-400 max-w-sm leading-relaxed">
                Autonomous Python Code Intelligence and Knowledge Graph Platform powered by AST parsing, Neo4j, ChromaDB, and Google Gemini.
              </p>
            </div>

            {/* Col 2: Navigation */}
            <div>
              <h4 className="text-xs font-mono uppercase tracking-wider font-bold text-slate-900 dark:text-white mb-3">
                Platform
              </h4>
              <ul className="space-y-2 text-sm text-slate-600 dark:text-slate-400">
                <li><a href="#" className="hover:text-indigo-600 dark:hover:text-indigo-400">Home</a></li>
                <li><a href="#features" className="hover:text-indigo-600 dark:hover:text-indigo-400">Features</a></li>
                <li><a href="#how-it-works" className="hover:text-indigo-600 dark:hover:text-indigo-400">Pipeline</a></li>
                <li><a href="#architecture" className="hover:text-indigo-600 dark:hover:text-indigo-400">Architecture</a></li>
              </ul>
            </div>

            {/* Col 3: Tech Stack */}
            <div>
              <h4 className="text-xs font-mono uppercase tracking-wider font-bold text-slate-900 dark:text-white mb-3">
                Technologies
              </h4>
              <ul className="space-y-2 text-sm text-slate-600 dark:text-slate-400">
                <li>Neo4j Graph Database</li>
                <li>ChromaDB Vector Store</li>
                <li>Google Gemini 3.5 API</li>
                <li>LangGraph Orchestration</li>
              </ul>
            </div>

          </div>

          {/* Bottom Bar */}
          <div className="pt-8 border-t border-slate-200 dark:border-white/5 flex flex-col sm:flex-row items-center justify-between text-xs text-slate-500 dark:text-slate-500 gap-4">
            <div>
              © 2026-2027 Cypher Platform. All rights reserved.
            </div>
            <div className="flex items-center gap-6">
              <span>Python 3.11+</span>
              <span>FastAPI Backend</span>
              <span>React 19 + Tailwind v4</span>
            </div>
          </div>

        </div>
      </footer>
    </>
  );
};
