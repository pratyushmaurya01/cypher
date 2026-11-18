import React from 'react';
import { 
  UploadCloud, 
  Workflow, 
  Share2, 
  Layers3, 
  Sparkles,
  ArrowRight
} from 'lucide-react';

const steps = [
  {
    step: "01",
    icon: UploadCloud,
    title: "Repository Upload",
    description: "Upload a ZIP archive or connect your Git repository. Files are securely isolated into isolated disk snapshots."
  },
  {
    step: "02",
    icon: Workflow,
    title: "AST Parsing",
    description: "Cypher's native AST visitors scan syntax trees, identifying modules, classes, functions, calls, imports, and variables."
  },
  {
    step: "03",
    icon: Share2,
    title: "Knowledge Graph",
    description: "Graph entities and their topological cross-file relationships are mapped into a high-performance Neo4j property graph."
  },
  {
    step: "04",
    icon: Layers3,
    title: "Hybrid Retrieval",
    description: "Queries trigger parallel graph traversal and ChromaDB vector search, synthesized via Reciprocal Rank Fusion."
  },
  {
    step: "05",
    icon: Sparkles,
    title: "AI Insights",
    description: "Google Gemini reasons over grounded code slices, delivering answers with zero hallucination and line citations."
  }
];

export const HowItWorks = () => {
  return (
    <section id="how-it-works" className="py-20 md:py-28 bg-slate-50/70 dark:bg-[#070b12] border-y border-slate-200/80 dark:border-white/5 relative">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto mb-16">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-violet-50 dark:bg-violet-950/60 text-violet-600 dark:text-violet-400 border border-violet-200/80 dark:border-violet-800/80 mb-3">
            System Pipeline
          </div>
          <h2 className="text-3xl sm:text-4xl font-extrabold text-slate-900 dark:text-white tracking-tight">
            How Cypher Operates
          </h2>
          <p className="mt-4 text-base sm:text-lg text-slate-600 dark:text-slate-400">
            From raw source code to actionable intelligence in five deterministic stages.
          </p>
        </div>

        {/* Steps Horizontal Grid */}
        <div className="grid grid-cols-1 md:grid-cols-5 gap-6 relative">
          
          {steps.map((item, idx) => {
            const Icon = item.icon;
            return (
              <div 
                key={idx}
                className="relative flex flex-col p-6 rounded-2xl bg-white dark:bg-[#0d121f] border border-slate-200/90 dark:border-white/10 shadow-sm hover:shadow-md transition-all group"
              >
                {/* Step indicator */}
                <div className="flex items-center justify-between mb-4">
                  <span className="text-xs font-mono font-bold text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/80 px-2 py-0.5 rounded">
                    {item.step}
                  </span>
                  <div className="w-9 h-9 rounded-xl bg-slate-100 dark:bg-white/5 flex items-center justify-center text-slate-700 dark:text-slate-300 group-hover:bg-indigo-600 group-hover:text-white transition-colors">
                    <Icon className="w-5 h-5" />
                  </div>
                </div>

                {/* Step Title */}
                <h3 className="text-base font-bold text-slate-900 dark:text-white mb-2">
                  {item.title}
                </h3>

                {/* Step description */}
                <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
                  {item.description}
                </p>

                {/* Connecting arrow for desktop between steps */}
                {idx < steps.length - 1 && (
                  <div className="hidden lg:block absolute -right-3 top-1/2 -translate-y-1/2 z-10 text-slate-300 dark:text-slate-700 pointer-events-none">
                    <ArrowRight className="w-5 h-5" />
                  </div>
                )}
              </div>
            );
          })}

        </div>

      </div>
    </section>
  );
};
