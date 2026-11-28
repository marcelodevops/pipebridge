pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh 'mkdir -p dist && echo "built" > dist/app.bin'
            }
        }
        stage('Test') {
            steps {
                // Missing explicit stash in Build and unstash here:
                // GitHub Actions executes Test in a clean runner where dist/ does not exist.
                sh 'test -f dist/app.bin && echo "found binary"'
            }
        }
    }
}
