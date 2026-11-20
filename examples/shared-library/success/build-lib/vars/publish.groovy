def call(String label) {
    packageSources(label)
    withCredentials([string(credentialsId: 'npm-token', variable: 'NPM_TOKEN')]) {
        sh 'test -n "$NPM_TOKEN" && printf %s ok > dist/seen.txt'
    }
    stash name: 'dist', includes: 'dist/**'
}

def packageSources(String label) {
    sh "mkdir -p dist && printf %s \"${label}\" > dist/marker.txt"
}
