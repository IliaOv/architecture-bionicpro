import React from 'react';
import AuthCallback from './components/AuthCallback';
import ReportPage from './components/ReportPage';

const App: React.FC = () => {
  const path = window.location.pathname.replace(/\/$/, '') || '/';

  if (path === '/callback') {
    return <AuthCallback />;
  }

  return (
    <div className="App">
      <ReportPage />
    </div>
  );
};

export default App;
