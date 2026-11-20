def call() {
    sh 'printf %s before > marker.txt'
    sh 'exit 1'
    stash name: 'dist', includes: 'marker.txt'
}
