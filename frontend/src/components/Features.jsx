import React from 'react';
import { 
  Binary, 
  Share2, 
  GitMerge, 
  MessageSquareCode, 
  ShieldAlert, 
  FileCheck2,
  ArrowUpRight
} from 'lucide-react';

const features = [
  {
    icon: Binary,
    title: "AST-Based Code Analysis",
    description: "Parses Python syntax trees using native AST visitors to detect exact definitions, function signatures, decorator patterns, and lexical scopes.",
    tag: "Static Analysis",
    color: "from-blue-500 to-indigo-500"
  },
  {
    icon: Share2,
    title: "Knowledge Graph Exploration",
    description: "Constructs interconnected property graphs in Neo4j with explicit CALLS, IMPORTS, DEFINES, and INHERITS relationships across multi-file repositories.",
    tag: "Graph DB",
    color: "from-indigo-500 to-purple-500"
  },
  {
    icon: GitMerge,
    title: "Hybrid Graph + Vector Retrieval",
    description: "Fuses semantic vector similarity (ChromaDB) with topological graph depth traversal using Reciprocal Rank Fusion (RRF) for optimal context relevance.",
    tag: "RRF Fusion",
    color: "from-purple-500 to-pink-500"
  },
  {
    icon: MessageSquareCode,
    title: "AI-Powered Codebase Chat",
    description: "Ask natural language architectural questions, debug race conditions, or trace request lifecycles with verified answers from Google Gemini.",
    tag: "Gemini 3.5",
    color: "from-emerald-500 to-teal-500"
  },
  {
    icon: ShieldAlert,
    title: "Dependency & Impact Analysis",
    description: "Predict the full blast-radius of deleting a field or altering a database column before pushing to production, revealing hidden runtime breaks.",
    tag: "Blast Radius",
    color: "from-amber-500 to-orange-500"
  },
  {
    icon: FileCheck2,
    title: "Source-Level Code References",
    description: "Zero hallucination guarantee: every answer quotes verified line slices directly read from disk snapshots, complete with exact line ranges.",
    tag: "0% Hallucination",
    color: "from-cyan-500 to-blue-500"
  }
];

export const Features = () => {
  return (
    <section id="features" className="py-20 md:py-28 relative">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto mb-16">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 border border-indigo-200/80 dark:border-indigo-800/80 mb-3">
            Core Capabilities
          </div>
          <h2 className="text-3xl sm:text-4xl font-extrabold text-slate-900 dark:text-white tracking-tight">
            Engineered for Deep Code Understanding
          </h2>
          <p className="mt-4 text-base sm:text-lg text-slate-600 dark:text-slate-400">
            Standard vector search loses multi-file execution paths. Cypher pairs semantic embeddings with property graphs for complete architectural awareness.
          </p>
        </div>

        {/* Feature Cards Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 lg:gap-8">
          {features.map((feat, idx) => {
            const Icon = feat.icon;
            return (
              <div 
                key={idx}
                className="group relative p-7 rounded-2xl bg-white dark:bg-[#0c101a] border border-slate-200 dark:border-white/10 hover:border-indigo-500/50 dark:hover:border-indigo-500/50 shadow-sm hover:shadow-xl dark:shadow-none hover:-translate-y-1 transition-all duration-300"
              >
                {/* Top card row: icon and tag */}
                <div className="flex items-center justify-between mb-5">
                  <div className={`w-12 h-12 rounded-xl bg-gradient-to-tr ${feat.color} flex items-center justify-center text-white shadow-md shadow-indigo-500/20 group-hover:scale-110 transition-transform`}>
                    <Icon className="w-6 h-6 stroke-[2]" />
                  </div>
                  <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-slate-100 dark:bg-white/5 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-white/10">
                    {feat.tag}
                  </span>
                </div>

                {/* Card Title */}
                <h3 className="text-lg font-bold text-slate-900 dark:text-white group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors flex items-center justify-between">
                  {feat.title}
                  <ArrowUpRight className="w-4 h-4 opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-all text-indigo-500" />
                </h3>

                {/* Card Description */}
                <p className="mt-2.5 text-sm text-slate-600 dark:text-slate-400 leading-relaxed">
                  {feat.description}
                </p>

                {/* Subtle bottom edge gradient bar on hover */}
                <div className="absolute inset-x-0 bottom-0 h-0.5 bg-gradient-to-r from-transparent via-indigo-500 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
            );
          })}
        </div>

      </div>
    </section>
  );
};
