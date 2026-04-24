import { useAppStore } from '@/store/useAppStore';
import { HelpPage } from './HelpPage';
import { HomePage } from './HomePage';
import { LoginPage } from './LoginPage';
import { ProtocolsPage } from './ProtocolsPage';
import { SetupPage } from './SetupPage';

export function PageRouter() {
  const page = useAppStore((s) => s.ui.page);
  switch (page) {
    case 'home':
      return <HomePage />;
    case 'login':
      return <LoginPage />;
    case 'setup':
      return <SetupPage />;
    case 'protocols':
      return <ProtocolsPage />;
    case 'help':
      return <HelpPage />;
  }
}
