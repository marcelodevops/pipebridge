pipeline {
    agent any
    stages {
        stage('Parallel Build') {
            parallel {
                stage('Branch A') {
                    steps {
                        sh 'mkdir -p out && echo "a" > out/data.txt'
                        stash name: 'shared-data', includes: 'out/**'
                    }
                }
                stage('Branch B') {
                    steps {
                        sh 'mkdir -p out && echo "b" > out/data.txt'
                        stash name: 'shared-data', includes: 'out/**'
                    }
                }
            }
        }
        stage('Consume') {
            steps {
                unstash 'shared-data'
                sh 'cat out/data.txt'
            }
        }
    }
}
