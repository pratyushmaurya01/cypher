import React from 'react';
import { ThemeProvider } from './context/ThemeContext';
import { Navbar } from './components/Navbar';
import { Hero } from './components/Hero';
import { Features } from './components/Features';
import { HowItWorks } from './components/HowItWorks';
import { ArchitecturePreview, WhyCypher } from './components/Architecture';
import { CtaAndFooter } from './components/CtaAndFooter';

export function App() {
  return (
    <ThemeProvider>
      <div className="min-h-screen bg-[var(--bg-page)] text-[var(--text-primary)] transition-colors selection:bg-indigo-500 selection:text-white">
        <Navbar />
        <main>
          <Hero />
          <Features />
          <HowItWorks />
          <ArchitecturePreview />
          <WhyCypher />
          <CtaAndFooter />
        </main>
      </div>
    </ThemeProvider>
  );
}

export default App;
