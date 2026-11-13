"""PyInstaller entry point; all workers share the bundled Python runtime."""
from karaoke.app import main

if __name__ == '__main__':
    main()
