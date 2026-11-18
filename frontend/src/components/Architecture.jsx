import React from 'react';
import { 
  Network, 
  Terminal, 
  Database, 
  CheckCircle2, 
  XCircle, 
  Zap, 
  ShieldCheck, 
  ArrowRight
} from 'lucide-react';

export const ArchitecturePreview = () => {
  return (
    <section id="architecture" className="py-20 md:py-28 relative">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto mb-16">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 border border-blue-200/80 dark:border-blue-800/80 mb-3">
            System Design
          </div>
          <h2 className="text-3xl sm:text-4xl font-extrabold text-slate-900 dark:text-white tracking-tight">
            Hybrid Graph + Vector Architecture
          </h2>
          <p className="mt-4 text-base sm:text-lg text-slate-600 dark:text-slate-400">
            How LangGraph orchestrates Neo4j, ChromaDB, and Gemini in a bounded, 2-LLM-call execution pipeline.
          </p>
        </div>

        {/* Architecture Layout Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
          
          {/* Left Diagram Block */}
          <div className="lg:col-span-7 bg-white dark:bg-[#0b0f19] p-6 sm:p-8 rounded-2xl border border-slate-200 dark:border-white/10 shadow-xl">
            
            <div className="space-y-4">
              {/* Layer 1: Ingestion & Query */}
              <div className="p-4 rounded-xl bg-slate-50 dark:bg-white/5 border border-slate-200 dark:border-white/5 flex flex-col sm:flex-row items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-indigo-600 text-white">
                    <Terminal className="w-4 h-4" />
                  </div>
                  <div>
                    <h4 className="text-sm font-bold text-slate-900 dark:text-white">Query Understanding (LLM 1)</h4>
                    <p className="text-xs text-slate-500">Gemini 3.5 extracts entities, intent & search bounds</p>
                  </div>
                </div>
                <span className="text-[11px] font-mono text-indigo-500 font-semibold px-2 py-0.5 rounded bg-indigo-50 dark:bg-indigo-950">
                  Call 1
                </span>
              </div>

              {/* Fan-Out Arrow */}
              <div className="flex justify-center text-xs font-mono text-slate-400">
                ↓ Parallel Fan-Out Execution
              </div>

              {/* Layer 2: Dual Storage (Neo4j & Chroma) */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="p-4 rounded-xl bg-indigo-50/50 dark:bg-indigo-950/20 border border-indigo-200/60 dark:border-indigo-800/40">
                  <div className="flex items-center gap-2 text-indigo-600 dark:text-indigo-400 mb-2">
                    <Network className="w-4 h-4" />
                    <span className="font-bold text-xs uppercase tracking-wider">Neo4j Property Graph</span>
                  </div>
                  <p className="text-xs text-slate-600 dark:text-slate-400">
                    Traverses 1-3 hops for callers, callees, routes, and inheritance hierarchies.
                  </p>
                </div>

                <div className="p-4 rounded-xl bg-emerald-50/50 dark:bg-emerald-950/20 border border-emerald-200/60 dark:border-emerald-800/40">
                  <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400 mb-2">
                    <Database className="w-4 h-4" />
                    <span className="font-bold text-xs uppercase tracking-wider">ChromaDB Vectors</span>
                  </div>
                  <p className="text-xs text-slate-600 dark:text-slate-400">
                    3072-dim embeddings for docstrings, semantic blocks, and cross-file comments.
                  </p>
                </div>
              </div>

              {/* Layer 3: RRF & Context Builder */}
              <div className="p-4 rounded-xl bg-slate-50 dark:bg-white/5 border border-slate-200 dark:border-white/5 flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-bold text-slate-900 dark:text-white">Reciprocal Rank Fusion (RRF)</h4>
                  <p className="text-xs text-slate-500">Normalizes and merges scores $\to$ Exact disk slice extraction</p>
                </div>
                <span className="text-[11px] font-mono text-emerald-500 font-semibold px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950">
                  No LLM / Local
                </span>
              </div>

              {/* Layer 4: Final Synthesis */}
              <div className="p-4 rounded-xl bg-gradient-to-r from-indigo-900/40 to-violet-900/30 border border-indigo-500/40 flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-bold text-white">Grounded Answer Generation (LLM 2)</h4>
                  <p className="text-xs text-indigo-200/80">Inline code citations, line numbers, and impact summaries</p>
                </div>
                <span className="text-[11px] font-mono text-indigo-300 font-semibold px-2 py-0.5 rounded bg-indigo-950 border border-indigo-700/50">
                  Call 2
                </span>
              </div>

            </div>

          </div>

          {/* Right Highlights Column */}
          <div className="lg:col-span-5 space-y-6">
            <div className="space-y-4">
              <div className="flex items-start gap-3">
                <div className="p-1 rounded-full bg-emerald-500/10 text-emerald-500 mt-1">
                  <Zap className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-base text-slate-900 dark:text-white">Bounded LLM Usage</h4>
                  <p className="text-sm text-slate-600 dark:text-slate-400 mt-0.5">
                    Strict maximum of 2 LLM calls per query, eliminating infinite reasoning loops and reducing API token costs.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3">
                <div className="p-1 rounded-full bg-indigo-500/10 text-indigo-500 mt-1">
                  <ShieldCheck className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-base text-slate-900 dark:text-white">Deterministic Cypher Security</h4>
                  <p className="text-sm text-slate-600 dark:text-slate-400 mt-0.5">
                    Cypher executes only pre-audited, parameterized graph templates — never unverified LLM-generated raw Cypher code.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3">
                <div className="p-1 rounded-full bg-violet-500/10 text-violet-500 mt-1">
                  <Database className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-base text-slate-900 dark:text-white">Disk-Verified Evidence Slices</h4>
                  <p className="text-sm text-slate-600 dark:text-slate-400 mt-0.5">
                    SourceCodeService reads the exact line numbers from the repository snapshot directly into context, preventing stale hallucinations.
                  </p>
                </div>
              </div>
            </div>

            <div className="pt-2">
              <a 
                href="#how-it-works"
                className="inline-flex items-center gap-2 text-sm font-semibold text-indigo-600 dark:text-indigo-400 hover:text-indigo-500"
              >
                Learn more about the retrieval pipeline
                <ArrowRight className="w-4 h-4" />
              </a>
            </div>
          </div>

        </div>

      </div>
    </section>
  );
};

export const WhyCypher = () => {
  return (
    <section id="why-cypher" className="py-20 md:py-28 bg-slate-50/50 dark:bg-[#07090e] border-t border-slate-200 dark:border-white/5">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto mb-16">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200/80 dark:border-emerald-800/80 mb-3">
            Comparison
          </div>
          <h2 className="text-3xl sm:text-4xl font-extrabold text-slate-900 dark:text-white tracking-tight">
            Why Generic RAG Fails for Code
          </h2>
          <p className="mt-4 text-base sm:text-lg text-slate-600 dark:text-slate-400">
            Vector search alone misses function calls, inheritance trees, and routing logic. Here is how Cypher fixes it.
          </p>
        </div>

        {/* Comparison Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse bg-white dark:bg-[#0c101a] rounded-2xl overflow-hidden border border-slate-200 dark:border-white/10 shadow-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-white/10 bg-slate-50/80 dark:bg-white/5 text-xs uppercase tracking-wider font-mono text-slate-500 dark:text-slate-400">
                <th className="py-4 px-6">Capability / Benchmark</th>
                <th className="py-4 px-6 text-slate-500">Standard Vector RAG</th>
                <th className="py-4 px-6 text-indigo-600 dark:text-indigo-400 font-bold">Cypher Code Intelligence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-white/5 text-sm">
              <tr>
                <td className="py-4 px-6 font-semibold text-slate-900 dark:text-white">Call Graph Traversal</td>
                <td className="py-4 px-6 text-rose-500 dark:text-rose-400 flex items-center gap-2">
                  <XCircle className="w-4 h-4" /> Cannot follow multi-file caller/callee paths
                </td>
                <td className="py-4 px-6 text-emerald-600 dark:text-emerald-400 font-medium">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4" /> Neo4j multi-hop relationship traversal
                  </div>
                </td>
              </tr>

              <tr>
                <td className="py-4 px-6 font-semibold text-slate-900 dark:text-white">Blast Radius Analysis</td>
                <td className="py-4 px-6 text-rose-500 dark:text-rose-400 flex items-center gap-2">
                  <XCircle className="w-4 h-4" /> Only keyword/similarity matching
                </td>
                <td className="py-4 px-6 text-emerald-600 dark:text-emerald-400 font-medium">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4" /> Explicit AST dependency propagation
                  </div>
                </td>
              </tr>

              <tr>
                <td className="py-4 px-6 font-semibold text-slate-900 dark:text-white">Hallucination Resistance</td>
                <td className="py-4 px-6 text-amber-500 dark:text-amber-400 flex items-center gap-2">
                  <XCircle className="w-4 h-4" /> Inexact chunk boundaries & invented functions
                </td>
                <td className="py-4 px-6 text-emerald-600 dark:text-emerald-400 font-medium">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4" /> 0% Hallucination: exact file and line citations
                  </div>
                </td>
              </tr>

              <tr>
                <td className="py-4 px-6 font-semibold text-slate-900 dark:text-white">Context Density</td>
                <td className="py-4 px-6 text-slate-500">Unfiltered chunk dumping</td>
                <td className="py-4 px-6 text-emerald-600 dark:text-emerald-400 font-medium">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4" /> Reciprocal Rank Fusion (RRF) optimized
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

      </div>
    </section>
  );
};
